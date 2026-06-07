#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vparfum supplemental feed builder.

Качает primary remarketing-фид OpenCart, парсит каждый товар и собирает
SUPPLEMENTAL-фид (TSV для Google Sheets / Merchant), который по g:id переопределяет:
  - price            EUR -> UAH (фикс валюты)
  - title            generic-оптимизированный, БЕЗ чужой ТМ (бренд-донор тут НЕ пишем)
  - description      чистый, без HTML-мусора и без донора
  - google_product_category  479 (парфюм) / 2789 (автопарфум-ароматизатор)
  - product_type, brand, identifier_exists=no, item_group_id, size, custom_label_*

Донор «за мотивами Louis Vuitton …» живёт ТОЛЬКО на сайте (органика), в фиде его нет.
"""

import html, re, sys, os, csv, urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "https://vparfum.com.ua/index.php?route=extension/feed/remarketing_feed"
NS = {"g": "http://base.google.com/ns/1.0"}

# Склонение семейства аромата (мн.ч. укр -> прил. для «{X} парфум»)
FAMILY_ADJ = {
    "цитрусові": "цитрусовий", "східні": "східний", "фужерні": "фужерний",
    "деревні": "деревний", "квіткові": "квітковий", "фруктові": "фруктовий",
    "пряні": "пряний", "шипрові": "шипровий", "акватичні": "акватичний",
    "гурманські": "гурманський", "шкіряні": "шкіряний", "тютюнові": "тютюновий",
    "альдегідні": "альдегідний", "зелені": "зелений", "водяні": "водяний",
    "мускусні": "мускусний", "амброві": "амбровий", "солодкі": "солодкий",
}
FAMILY_SLUG = {
    "цитрусові": "citrus", "східні": "oriental", "фужерні": "fougere",
    "деревні": "woody", "квіткові": "floral", "фруктові": "fruity",
    "пряні": "spicy", "шипрові": "chypre", "акватичні": "aquatic",
    "гурманські": "gourmand", "шкіряні": "leather", "тютюнові": "tobacco",
    "альдегідні": "aldehyde", "зелені": "green", "водяні": "aquatic",
    "мускусні": "musk", "амброві": "amber", "солодкі": "sweet",
}

# Метки в описании (для нарезки слипшихся блоков OpenCart).
# Кавычки нормализуются ДО матча, поэтому «Нота «серця»» = «Нота серця».
# Длинные метки раньше коротких, чтобы «Класифікація аромату» не съелось «Класифікація».
LABELS = [
    "Класифікація аромату", "Класифікація", "Тип аромату",
    "Початкова нота", "Верхня нота", "Верхняя нота", "Верхние ноты",
    "Нота серця", "Середня нота", "Средние ноты", "Средняя нота",
    "Кінцева нота", "Базова нота", "Базовые ноты", "Базовая нота",
]
TOP_KEYS = ["Початкова нота", "Верхня нота", "Верхняя нота", "Верхние ноты"]
_LABEL_RE = re.compile("(" + "|".join(sorted(LABELS, key=len, reverse=True)) + ")", re.IGNORECASE)


def clean(text):
    """Двойной un-escape + убрать nbsp/мусор + нормализовать кавычки."""
    if not text:
        return ""
    t = html.unescape(html.unescape(text))
    t = t.replace("\xa0", " ").replace("​", " ")
    t = re.sub(r"[«»\"„“”‘’']", "", t)  # все кавычки прочь (нота «серця» -> нота серця)
    return re.sub(r"\s+", " ", t).strip()


def parse_desc(raw):
    """Вернуть dict метка->значение, разрезав слипшиеся блоки (регистронезависимо)."""
    t = _LABEL_RE.sub(lambda m: "\n" + m.group(1), clean(raw))
    out = {}
    for line in t.split("\n"):
        line = line.strip(" :;.,")
        low = line.lower()
        for lab in LABELS:
            if low.startswith(lab.lower()):
                val = line[len(lab):].strip(" :;.,").strip()
                if val and lab not in out:
                    out[lab] = val
                break
    return out


def notes_lower(val):
    parts = [p.strip() for p in re.split(r"[,;]", val) if p.strip()]
    return ", ".join(p.lower() for p in parts[:4])  # до 4 нот


def slugify(s):
    s = s.lower()
    translit = {"а":"a","б":"b","в":"v","г":"h","ґ":"g","д":"d","е":"e","є":"ie",
        "ж":"zh","з":"z","и":"y","і":"i","ї":"i","й":"i","к":"k","л":"l","м":"m",
        "н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"kh",
        "ц":"ts","ч":"ch","ш":"sh","щ":"shch","ь":"","ю":"iu","я":"ia"}
    s = "".join(translit.get(ch, ch) for ch in s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def build_rows(xml_bytes):
    root = ET.fromstring(xml_bytes)
    rows = []
    for item in root.iter("item"):
        gid = item.findtext("g:id", default="", namespaces=NS).strip()
        raw_title = clean(item.findtext("g:title", default="", namespaces=NS))
        raw_desc = item.findtext("g:description", default="", namespaces=NS)
        price_raw = item.findtext("g:price", default="", namespaces=NS)
        if not gid or not raw_title:
            continue

        is_auto = raw_title.startswith("Автопарфум")
        # модель + объём из названия
        m = re.match(r"(?:Авто)?[Пп]арфум\s+Vparfum\s+(.+?)\s*(\d+)\s*ml", raw_title)
        if m:
            model, vol_num = m.group(1).strip(), m.group(2)
        else:
            model = re.sub(r"(?:Авто)?[Пп]арфум\s+Vparfum\s+", "", raw_title)
            vol_num = (re.search(r"(\d+)\s*ml", raw_title) or ["", ""])[1] if re.search(r"(\d+)\s*ml", raw_title) else ""
        volume = f"{vol_num} мл" if vol_num else ""

        d = parse_desc(raw_desc)
        family_raw = d.get("Тип аромату", "")
        family_first = re.split(r"[,;/]", family_raw)[0].strip().lower() if family_raw else ""
        family_adj = FAMILY_ADJ.get(family_first, family_first)
        family_slug = FAMILY_SLUG.get(family_first, "other" if not family_first else slugify(family_first))

        top = ""
        for k in TOP_KEYS:
            if d.get(k):
                top = notes_lower(d[k]); break

        price_num = (re.search(r"([\d.]+)", price_raw) or ["", "0"])[1]
        price = f"{price_num} UAH"

        # ---- generic feed-title (без донора) ----
        tester = " тестер" if (not is_auto and vol_num == "10") else ""
        kind = "автопарфум (ароматизатор для авто)" if is_auto else "парфум"
        bits = [f"Vparfum {model} {volume}{tester}".strip().rstrip(",")]
        if family_adj and not is_auto:
            bits.append(f"{family_adj} {kind}")
        elif is_auto:
            bits.append("ароматизатор для авто Vparfum")
        else:
            bits.append(kind)
        if top:
            bits.append(top)
        title = ", ".join(b for b in bits if b)
        title = title[:148]

        # ---- clean description ----
        all_notes = []
        for k in ["Початкова нота","Верхня нота","Верхняя нота","Верхние ноты",
                  "Нота серця","Средние ноты","Кінцева нота","Базова нота","Базовые ноты"]:
            if d.get(k):
                all_notes.append(clean(d[k]).lower())
        notes_str = "; ".join(dict.fromkeys(all_notes))  # уникальные, порядок
        if is_auto:
            desc = (f"Автопарфум Vparfum {model}, ароматизатор для авто, {volume}. "
                    f"{('Ноти: ' + notes_str + '. ') if notes_str else ''}Власне виробництво, доставка по Україні.")
            cat = "2789"
            ptype = "Автотовари > Ароматизатори для авто"
            grp = f"vp-{slugify(model)}-auto"
        else:
            fam_txt = f"{family_adj} " if family_adj else ""
            desc = (f"{fam_txt.capitalize()}парфум Vparfum {model}, {volume}. "
                    f"{('Ноти: ' + notes_str + '. ') if notes_str else ''}"
                    f"Власне виробництво, доставка по Україні.").replace("  ", " ")
            cat = "479"
            ptype = f"Парфумерія > {family_raw.capitalize()} аромати" if family_raw else "Парфумерія"
            grp = f"vp-{slugify(model)}-parfum"

        rows.append({
            "id": gid,
            "title": title,
            "description": desc.strip(),
            "price": price,
            "google_product_category": cat,
            "product_type": ptype,
            "brand": "Vparfum",
            "identifier_exists": "no",
            "item_group_id": grp,
            "size": volume,
            "custom_label_0": f"{vol_num}ml" if vol_num else "",
            "custom_label_1": "car_parfum" if is_auto else "personal_parfum",
            "custom_label_2": family_slug,
        })
    return rows


# Минимальный supplemental (решение дебатов): переопределяем ТОЛЬКО проблемные поля,
# не дублируем товар. БЕЗ description (его даёт primary, он раздувает фид вдвое).
SUPP_COLS = ["id", "title", "price", "google_product_category", "identifier_exists",
             "brand", "custom_label_0", "custom_label_1", "custom_label_2"]

OUT_CSV = os.path.join("docs", "vparfum-supplemental.csv")
MIN_ITEMS = 600   # safety-порог: ниже = битый/обрезанный фид OpenCart, не публикуем (стабильно 780)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else FEED_URL
    if src.startswith("http"):
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        xml_bytes = urllib.request.urlopen(req, timeout=60).read()
    else:
        xml_bytes = open(src, "rb").read()

    rows = build_rows(xml_bytes)

    # Safety: не перезаписываем хороший CSV битым ответом OpenCart
    if len(rows) < MIN_ITEMS:
        sys.stderr.write(f"СТОП: получено {len(rows)} товаров (< порога {MIN_ITEMS}). "
                         f"Похоже на обрезанный/битый фид. Не публикую, прерываюсь.\n")
        sys.exit(1)

    os.makedirs("docs", exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(SUPP_COLS)
        for r in rows:
            w.writerow([str(r.get(c, "")) for c in SUPP_COLS])

    auto = sum(1 for r in rows if r["custom_label_1"] == "car_parfum")
    print(f"OK: {len(rows)} товаров -> {OUT_CSV} ({len(SUPP_COLS)} колонок)")
    print(f"   личных парфюмов: {len(rows)-auto} | автопарфумов: {auto}")
    print("\n--- ОБРАЗЕЦ: Symphony 10ml (id 1616) ---")
    for r in rows:
        if r["id"] == "1616":
            for c in SUPP_COLS:
                print(f"  {c:24}: {r[c]}")
            break


if __name__ == "__main__":
    main()
