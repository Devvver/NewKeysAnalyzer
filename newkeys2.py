import streamlit as st
import pandas as pd
import datetime
import requests
import time
import os
from urllib.parse import urlparse
from xml.etree import ElementTree
from google.oauth2 import service_account
from googleapiclient.discovery import build


# --- ФУНКЦИИ API ---

def get_gsc_service_sa():
    """Авторизация через Service Account"""
    try:
        if not os.path.exists('credentials.json'):
            st.error("❌ Файл credentials.json не найден!")
            st.stop()
        creds = service_account.Credentials.from_service_account_file(
            'credentials.json',
            scopes=['https://www.googleapis.com/auth/webmasters.readonly']
        )
        return build('searchconsole', 'v1', credentials=creds)
    except Exception as e:
        st.error(f"Ошибка авторизации: {e}")
        st.stop()


def get_urls_from_sitemap(url):
    """Парсинг URL из Sitemap XML"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, headers=headers, timeout=20)
        res.raise_for_status()
        tree = ElementTree.fromstring(res.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = [loc.text for loc in tree.findall(".//ns:loc", ns)]
        return urls
    except Exception as e:
        st.error(f"Ошибка при загрузке Sitemap: {e}")
        return []


def fetch_detailed_keys(service, site, page, start, end):
    """Получение ключей с показами, кликами и позициями"""
    body = {
        'startDate': start,
        'endDate': end,
        'dimensions': ['query'],
        'dimensionFilterGroups': [{
            'filters': [{
                'dimension': 'page',
                'operator': 'equals',
                'expression': page
            }]
        }],
        'rowLimit': 5000
    }
    try:
        response = service.searchanalytics().query(siteUrl=site, body=body).execute()
        rows = response.get('rows', [])
        # Округляем позицию до десятых для хранения в данных
        return {r['keys'][0]: {
            'clicks': int(r['clicks']),
            'impressions': int(r['impressions']),
            'position': round(r['position'], 1)
        } for r in rows}
    except Exception:
        return {}


def get_month_range(year, month_idx):
    """Превращает год и месяц в даты ГГГГ-ММ-ДД для API"""
    start_date = datetime.date(year, month_idx, 1)
    if month_idx == 12:
        end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end_date = datetime.date(year, month_idx + 1, 1) - datetime.timedelta(days=1)
    return start_date.isoformat(), end_date.isoformat()


# --- ИНТЕРФЕЙС STREAMLIT ---

st.set_page_config(page_title="GSC New Keys Analyzer PRO", layout="wide")
st.title("🚀 Поиск новых ключей")

# Инициализация хранилища (чтобы результат не пропадал)
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None

MONTHS_LIST = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
               "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_DICT = {name: i + 1 for i, name in enumerate(MONTHS_LIST)}

with st.sidebar:
    st.header("Настройки")
    sitemap_url = st.text_input("URL Sitemap.xml", placeholder="https://example.com/sitemap.xml")

    st.divider()
    st.subheader("Выбор периодов")

    today = datetime.date.today()
    # Логика дефолтов (Январь vs Декабрь, если сегодня Февраль)
    first_day_this_month = today.replace(day=1)
    last_month_dt = first_day_this_month - datetime.timedelta(days=1)
    prev_month_dt = last_month_dt.replace(day=1) - datetime.timedelta(days=1)

    # 1. Месяц анализа
    st.write("**Месяц анализа:**")
    col1_y, col1_m = st.columns(2)
    with col1_y:
        y1 = st.selectbox("Год", [today.year, today.year - 1],
                          index=0 if last_month_dt.year == today.year else 1, key="y1")
    with col1_m:
        m1 = st.selectbox("Месяц", MONTHS_LIST, index=last_month_dt.month - 1, key="m1")

    # 2. Базовый месяц
    st.write("**С чем сравниваем (База):**")
    col2_y, col2_m = st.columns(2)
    with col2_y:
        y2 = st.selectbox("Год базы", [today.year, today.year - 1],
                          index=0 if prev_month_dt.year == today.year else 1, key="y2")
    with col2_m:
        m2 = st.selectbox("Месяц базы", MONTHS_LIST, index=prev_month_dt.month - 1, key="m2")

    st.info("Выбраны прошлый и позапрошлый месяцы для полноты данных GSC.")

if st.button(" Парсинг"):
    if not sitemap_url:
        st.warning("Введите URL Sitemap!")
    else:
        service = get_gsc_service_sa()
        all_urls = get_urls_from_sitemap(sitemap_url)

        if not all_urls:
            st.error("Sitemap пуст или недоступен.")
        else:
            # Авто-определение ресурса из первой ссылки Sitemap
            parsed_uri = urlparse(all_urls[0])
            site_url = f'{parsed_uri.scheme}://{parsed_uri.netloc}/'


            cur_start, cur_end = get_month_range(y1, MONTHS_DICT[m1])
            prev_start, prev_end = get_month_range(y2, MONTHS_DICT[m2])

            total = len(all_urls)
            progress_bar = st.progress(0)
            status_text = st.empty()
            temp_results = []

            for i, url in enumerate(all_urls):
                status_text.text(f"Обработка {i + 1}/{total}")

                # Получаем данные за два периода
                data_now = fetch_detailed_keys(service, site_url, url, cur_start, cur_end)
                data_prev = fetch_detailed_keys(service, site_url, url, prev_start, prev_end)

                # Сравниваем запросы
                new_queries = set(data_now.keys()) - set(data_prev.keys())

                if new_queries:
                    metrics_list = []
                    for q in new_queries:
                        m = data_now[q]
                        metrics_list.append({
                            "Запрос": q,
                            "Показы": m['impressions'],
                            "Клики": m['clicks'],
                            "Позиция": m['position']
                        })

                    temp_results.append({
                        "URL": url,
                        "Count": len(new_queries),
                        "Metrics": metrics_list
                    })

                progress_bar.progress((i + 1) / total)
                if i % 10 == 0:
                    time.sleep(0.02)

            status_text.empty()
            st.session_state.analysis_results = temp_results

# --- ВЫВОД РЕЗУЛЬТАТОВ ---

if st.session_state.analysis_results:
    res_list = st.session_state.analysis_results
    # Сортировка по кол-ву новых ключей (Топ-50)
    sorted_res = sorted(res_list, key=lambda x: x['Count'], reverse=True)[:50]

    st.divider()
    st.subheader(f"🔥 Результаты анализа: {m1} {y1} против {m2} {y2}")

    for idx, row in enumerate(sorted_res):
        with st.expander(f"➕ {row['Count']} новых — {row['URL']}"):
            df = pd.DataFrame(row['Metrics'])
            df = df.sort_values(by="Показы", ascending=False)

            st.write("**Метрики новых запросов:**")

            # Принудительное форматирование вывода: десятичные для позиций
            st.table(df.style.format({
                "Позиция": "{:.1f}",
                "Показы": "{:,.0f}",
                "Клики": "{:,.0f}"
            }))

            st.write("**Список запросов (для копирования):**")
            clean_keys = "\n".join(df["Запрос"].tolist())
            st.text_area(label="Текстовый список:", value=clean_keys, height=180, key=f"txt_{idx}")
            st.divider()