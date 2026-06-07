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

# Семейство аромата → мужской род (для description: «цитрусовий аромат»)
FAMILY_ADJ = {
    "цитрусові": "цитрусовий", "східні": "східний", "фужерні": "фужерний",
    "деревні": "деревний", "деревинні": "деревний", "квіткові": "квітковий",
    "фруктові": "фруктовий", "пряні": "пряний", "шипрові": "шипровий",
    "акватичні": "акватичний", "гурманські": "гурманський", "шкіряні": "шкіряний",
    "тютюнові": "тютюновий", "альдегідні": "альдегідний", "зелені": "зелений",
    "водяні": "водяний", "мускусні": "мускусний", "амброві": "амбровий",
    "солодкі": "солодкий", "ароматичні": "ароматний",
}
# Семейство → женский род (для title под «Парфумована вода ___»)
FAMILY_ADJ_FEM = {
    "цитрусові": "цитрусова", "східні": "східна", "фужерні": "фужерна",
    "деревні": "деревна", "деревинні": "деревна", "квіткові": "квіткова",
    "фруктові": "фруктова", "пряні": "пряна", "шипрові": "шипрова",
    "акватичні": "акватична", "гурманські": "гурманська", "шкіряні": "шкіряна",
    "тютюнові": "тютюнова", "альдегідні": "альдегідна", "зелені": "зелена",
    "водяні": "водяна", "мускусні": "мускусна", "амброві": "амброва",
    "солодкі": "солодка", "ароматичні": "ароматна",
}
FAMILY_SLUG = {
    "цитрусові": "citrus", "східні": "oriental", "фужерні": "fougere",
    "деревні": "woody", "деревинні": "woody", "квіткові": "floral",
    "фруктові": "fruity", "пряні": "spicy", "шипрові": "chypre",
    "акватичні": "aquatic", "гурманські": "gourmand", "шкіряні": "leather",
    "тютюнові": "tobacco", "альдегідні": "aldehyde", "зелені": "green",
    "водяні": "aquatic", "мускусні": "musk", "амброві": "amber",
    "солодкі": "sweet", "ароматичні": "aromatic",
}
# Белый список: family валиден только если в нём (иначе мусорный парсинг → family="")
FAMILY_VALID = set(FAMILY_ADJ_FEM.keys())

# ── Словари для DESCRIPTION (по family_key — англ. slug) ──
# Вывод семейства из ноты, когда поля «Тип аромату» нет (а его нет у 70% товаров)
NOTE_TO_FAMILY = {
    "бергамот": "citrus", "лимон": "citrus", "грейпфрут": "citrus", "нероли": "citrus",
    "неролі": "citrus", "мандарин": "citrus", "апельсин": "citrus", "лайм": "citrus", "цитрон": "citrus",
    "кедр": "woody", "ветивер": "woody", "ветівер": "woody", "сандал": "woody", "сандалове дерево": "woody",
    "пачулі": "woody", "пачули": "woody", "деревні ноти": "woody",
    "троянда": "floral", "жасмин": "floral", "півонія": "floral", "фіалка": "floral",
    "ірис": "floral", "тубероза": "floral", "конвалія": "floral", "квіти": "floral", "білі квіти": "floral",
    "ваніль": "oriental", "амбра": "oriental", "бензоїн": "oriental", "ладан": "oriental", "олібанум": "oriental",
    "лаванда": "fougere", "дубовий мох": "chypre", "мох": "chypre",
    "карамель": "gourmand", "праліне": "gourmand", "шоколад": "gourmand", "мед": "gourmand",
    "тонка": "gourmand", "боби тонка": "gourmand", "кава": "gourmand", "капучино": "gourmand",
    "мускус": "musk", "перець": "spicy", "імбир": "spicy", "кардамон": "spicy",
    "кориця": "spicy", "шафран": "spicy", "диня": "fruity", "яблуко": "fruity",
    "малина": "fruity", "ананас": "fruity", "груша": "fruity", "персик": "fruity",
}
FEM_BY_KEY = {
    "citrus": "цитрусова", "woody": "деревна", "floral": "квіткова", "oriental": "східна амброва",
    "fougere": "фужерна", "chypre": "шипрова", "gourmand": "солодка гурманська",
    "aquatic": "акватична свіжа", "musk": "мускусна", "spicy": "пряна", "fruity": "фруктова",
    "green": "зелена", "aldehyde": "альдегідна", "leather": "шкіряна", "tobacco": "тютюнова",
    "amber": "східна амброва", "sweet": "солодка", "fruity": "фруктова", "aromatic": "ароматна",
}
CHAR_BY_KEY = {
    "citrus": "Свіже, бадьоре звучання з прозорою енергією.",
    "woody": "Глибокий, теплий характер із благородною деревною основою.",
    "floral": "М'яке, елегантне квіткове звучання.",
    "oriental": "Чуттєвий, обволікаючий шлейф із пряною теплотою.",
    "amber": "Чуттєвий, обволікаючий шлейф із пряною теплотою.",
    "fougere": "Чистий, динамічний характер зі свіжою прохолодою.",
    "chypre": "Витончене шипрове звучання з благородною гірчинкою.",
    "gourmand": "Затишне солодке звучання з десертними відтінками.",
    "sweet": "Затишне солодке звучання з десертними відтінками.",
    "aquatic": "Прозоре, освіжаюче морське звучання.",
    "musk": "М'яке пудрове мускусне звучання.",
    "spicy": "Пряне, зігрівальне звучання з характером.",
    "fruity": "Соковите, грайливе фруктове звучання.",
}
SEASON_BY_KEY = {
    "citrus": "теплу пору року", "aquatic": "теплу пору року", "fougere": "теплу пору року",
    "fruity": "теплу пору року", "oriental": "прохолодний сезон", "amber": "прохолодний сезон",
    "woody": "прохолодний сезон", "gourmand": "прохолодний сезон", "sweet": "прохолодний сезон",
    "spicy": "прохолодний сезон",
}
AUTO_CHAR_BY_KEY = {
    "citrus": "Свіже цитрусове звучання", "woody": "Тепле деревне звучання",
    "floral": "Ніжне квіткове звучання", "oriental": "Пряне обволікаюче звучання",
    "amber": "Пряне обволікаюче звучання", "gourmand": "Солодке десертне звучання",
    "sweet": "Солодке десертне звучання", "aquatic": "Свіже морське звучання",
    "fougere": "Чисте прохолодне звучання", "chypre": "Витончене шипрове звучання",
    "musk": "М'яке мускусне звучання", "spicy": "Пряне зігрівальне звучання",
    "fruity": "Соковите фруктове звучання",
}
CHAR_FALLBACK = "Багатогранне, збалансоване звучання."
AUTO_CHAR_FALLBACK = "Збалансоване ароматне звучання"


def notes_phrase(top):
    """'імбир, бергамот, грейпфрут' -> 'імбир, бергамот та грейпфрут'"""
    parts = [p.strip() for p in top.split(",") if p.strip()][:3]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " та " + parts[-1]


def infer_family_key(family_first, top):
    """family_key из поля, иначе выводим из top-нот."""
    if family_first in FAMILY_VALID:
        return FAMILY_SLUG.get(family_first, "")
    for note in [p.strip().lower() for p in top.split(",")]:
        if note in NOTE_TO_FAMILY:
            return NOTE_TO_FAMILY[note]
    return ""

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
        # модель + объём (объём бывает латиницей «ml» у парфюмов и кириллицей «мл» у авто)
        VOL = r"(\d+)\s*(?:ml|мл)"
        m = re.match(r"(?:Авто)?[Пп]арфум\s+Vparfum\s+(.+?)\s*" + VOL, raw_title)
        if m:
            model, vol_num = m.group(1).strip(), m.group(2)
        else:
            model = re.sub(r"(?:Авто)?[Пп]арфум\s+Vparfum\s+", "", raw_title)
            mv = re.search(VOL, raw_title)
            vol_num = mv.group(1) if mv else ""
            model = re.sub(VOL, "", model).strip()   # вырезать объём из модели
        volume = f"{vol_num} мл" if vol_num else ""

        d = parse_desc(raw_desc)
        family_raw = d.get("Тип аромату", "")
        family_first = re.split(r"[,;/]", family_raw)[0].strip().lower() if family_raw else ""
        if family_first not in FAMILY_VALID:      # белый список: отсекаем мусорный парсинг family
            family_first = ""
        family_adj = FAMILY_ADJ.get(family_first, "")        # муж. род — для description
        family_fem = FAMILY_ADJ_FEM.get(family_first, "")    # жен. род — для title под «вода»
        family_slug = FAMILY_SLUG.get(family_first, "other")

        # ключевые ноты — ТОЛЬКО для вплетения в описание, в title НЕ идут
        top = ""
        for k in TOP_KEYS:
            if d.get(k):
                top = notes_lower(d[k]); break
        top3 = ", ".join(top.split(", ")[:3]) if top else ""

        price_num = (re.search(r"([\d.]+)", price_raw) or ["", "0"])[1]
        price = f"{price_num} UAH"

        # ---- TITLE: широкий ключ -> уточняющий, без нот, без чужой ТМ ----
        if is_auto:
            # cat 2789: широкий ключ авто-категории первым словом
            title = f"Ароматизатор для авто Vparfum {model} парфум для машини {volume}"
        else:
            # cat 479: «Парфумована вода [семейство-фем] Vparfum [модель] [объём] [тестер]»
            bits = ["Парфумована вода"]
            if family_fem:
                bits.append(family_fem)            # уточнение вплотную к «вода»
            bits += ["Vparfum", model, volume]      # бренд на 3-й позиции, не первой
            if vol_num == "10":
                bits.append("тестер")
            title = " ".join(b for b in bits if b)
        title = re.sub(r"\s+", " ", title).strip()[:148]

        # ---- DESCRIPTION: чистое товарное, БЕЗ доставки/магазина/промо (синтез 2 маркетологов) ----
        family_key = infer_family_key(family_first, top)   # из поля ИЛИ из нот
        notes_txt = notes_phrase(top)
        if is_auto:
            auto_char = AUTO_CHAR_BY_KEY.get(family_key, AUTO_CHAR_FALLBACK)
            notes_blk = f" з нотами {notes_txt}" if notes_txt else ""
            desc = (f"Ароматизатор для авто {model}, автопарфум для салону, об'єм {volume}. "
                    f"{auto_char}{notes_blk} наповнює салон ненав'язливо й тримається довго. "
                    "Освіжає повітря в машині та створює приємну атмосферу в дорозі. "
                    "Підійде у власне авто або як подарунок водієві. "
                    "Парфумована композиція за мотивами світової парфумерії, підходить для авто, дому та офісу.")
            cat, grp = "2789", f"vp-{slugify(model)}-auto"
        else:
            fem = FEM_BY_KEY.get(family_key, "")
            char = CHAR_BY_KEY.get(family_key, CHAR_FALLBACK)
            season = SEASON_BY_KEY.get(family_key, "")
            tester_blk = ", формат тестер" if vol_num == "10" else ""
            notes_blk = f" У звучанні переплітаються {notes_txt}." if notes_txt else ""
            season_blk = f", добре звучить у {season}" if season else ""
            head_fem = f"{fem} " if fem else ""
            desc = (f"Парфумована вода унісекс {head_fem}{model}, об'єм {volume}{tester_blk}. "
                    f"{char}{notes_blk} "
                    "Розкривається близько до шкіри, лишає делікатний ароматний шлейф. "
                    f"Пасує для щоденного носіння, офісу та особливих подій{season_blk}. "
                    "Нішевий селективний аромат за мотивами світової парфумерії для тих, хто шукає несхожі духи з характером.")
            cat, grp = "479", f"vp-{slugify(model)}-parfum"
        desc = re.sub(r"\s+", " ", desc).strip()

        rows.append({
            "id": gid,
            "title": title,
            "description": desc,
            "price": price,
            "google_product_category": cat,
            "identifier_exists": "no",
            "brand": "Vparfum",
            "item_group_id": grp,
            "size": volume,
            "custom_label_0": f"{vol_num}ml" if vol_num else "",
            "custom_label_1": "car_parfum" if is_auto else "personal_parfum",
            "custom_label_2": family_key or "other",
        })
    return rows


# Supplemental: переопределяем проблемные поля. description ВЕРНУЛИ (решение 2-х
# Shopping-спецов) — primary OpenCart отдаёт HTML-мусор, перекрываем чистым текстом.
SUPP_COLS = ["id", "title", "description", "price", "google_product_category",
             "identifier_exists", "brand", "custom_label_0", "custom_label_1", "custom_label_2"]

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
