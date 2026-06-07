# Vparfum Feed Cleaner

Трансформирует Google-remarketing фид OpenCart (`vparfum.com.ua`) в **supplemental-фид** для Google Merchant Center.

## Что чинит
- **Валюта** EUR → UAH (primary-фид OpenCart отдаёт битые EUR)
- **google_product_category**: `479` (личный парфюм) / `2789` (автопарфум-ароматизатор)
- **identifier_exists**: `no` (собственное производство, GTIN нет)
- **title**: оптимизированный generic (Vparfum + модель + объём + семейство + ноты), без чужой ТМ
- **custom_label_0..2**: объём / тип / семейство аромата — для PMax

Связь с primary по ключу `id` (числовой OpenCart product_id).

## Выход
Публичный CSV (GitHub Pages, ветка main `/docs`):
```
https://killertrafic-lgtm.github.io/vparfum-feed-cleaner/vparfum-supplemental.csv
```

## Авто-обновление
GitHub Actions (`.github/workflows/update-feed.yml`) запускается ежечасно: тянет свежий фид → `transform.py` → пишет `docs/vparfum-supplemental.csv` → коммитит, если изменилось. Safety-порог 600 товаров (ниже — битый фид, не публикуем).

## Подключение
- **Merchant Center**: Источники данных → Дополнительный → запланированная выборка (URL выше) → ежечасно → связать с primary по `id`.
- **Живая таблица** (Drive Ильи): `=IMPORTDATA("URL выше")` в ячейке A1.

## Ручной запуск
```bash
python3 transform.py            # тянет живой фид
python3 transform.py feed.xml   # из локального файла
```
