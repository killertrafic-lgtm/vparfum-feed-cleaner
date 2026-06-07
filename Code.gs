/**
 * Vparfum Supplemental Feed builder (Google Apps Script).
 * Тянет primary remarketing-фид OpenCart, чинит валюту EUR->UAH,
 * собирает оптимизированные title/description, проставляет категории
 * и пишет всё в активный лист = supplemental-фид для Google Merchant.
 *
 * Установка:
 *   1. Розширення -> Apps Script, вставити цей файл, зберегти.
 *   2. Запустити rebuild() один раз (дозволити доступ).
 *   3. Меню «Vparfum Feed» -> «Увімкнути авто-оновлення» (щодня о 4:00).
 *   4. У Merchant підключити цю таблицю як supplemental, ключ id.
 */

var FEED_URL = 'https://vparfum.com.ua/index.php?route=extension/feed/remarketing_feed';

var COLS = ['id','title','description','price','google_product_category','product_type',
            'brand','identifier_exists','item_group_id','size',
            'custom_label_0','custom_label_1','custom_label_2'];

var FAMILY_ADJ = {
  'цитрусові':'цитрусовий','східні':'східний','фужерні':'фужерний','деревні':'деревний',
  'квіткові':'квітковий','фруктові':'фруктовий','пряні':'пряний','шипрові':'шипровий',
  'акватичні':'акватичний','гурманські':'гурманський','шкіряні':'шкіряний','тютюнові':'тютюновий',
  'альдегідні':'альдегідний','зелені':'зелений','водяні':'водяний','мускусні':'мускусний',
  'амброві':'амбровий','солодкі':'солодкий'
};
var FAMILY_SLUG = {
  'цитрусові':'citrus','східні':'oriental','фужерні':'fougere','деревні':'woody',
  'квіткові':'floral','фруктові':'fruity','пряні':'spicy','шипрові':'chypre',
  'акватичні':'aquatic','гурманські':'gourmand','шкіряні':'leather','тютюнові':'tobacco',
  'альдегідні':'aldehyde','зелені':'green','водяні':'aquatic','мускусні':'musk',
  'амброві':'amber','солодкі':'sweet'
};
var LABELS = ['Класифікація аромату','Класифікація','Тип аромату','Початкова нота','Верхня нота',
  'Верхняя нота','Верхние ноты','Нота серця','Середня нота','Средние ноты','Средняя нота',
  'Кінцева нота','Базова нота','Базовые ноты','Базовая нота'];
var TOP_KEYS = ['Початкова нота','Верхня нота','Верхняя нота','Верхние ноты'];
var ALL_NOTE_KEYS = ['Початкова нота','Верхня нота','Верхняя нота','Верхние ноты',
  'Нота серця','Средние ноты','Кінцева нота','Базова нота','Базовые ноты'];

var _labelRe = new RegExp('(' + LABELS.slice().sort(function(a,b){return b.length-a.length;}).join('|') + ')', 'gi');

function decodeText(s){
  if(!s) return '';
  for(var i=0;i<2;i++){
    s = s.replace(/&amp;/g,'&').replace(/&nbsp;/g,' ').replace(/&apos;/g,"'")
         .replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&#39;/g,"'");
  }
  s = s.replace(/[«»"„“”‘’']/g,'').replace(/ /g,' ');
  return s.replace(/\s+/g,' ').trim();
}

function parseDesc(raw){
  var t = decodeText(raw).replace(_labelRe, function(m){ return '\n' + m; });
  var lines = t.split('\n'), out = {};
  for(var i=0;i<lines.length;i++){
    var line = lines[i].replace(/^[\s:;.,]+|[\s:;.,]+$/g,'');
    var low = line.toLowerCase();
    for(var j=0;j<LABELS.length;j++){
      var lab = LABELS[j];
      if(low.indexOf(lab.toLowerCase())===0){
        var val = line.substring(lab.length).replace(/^[\s:;.,]+|[\s:;.,]+$/g,'');
        if(val && !out[lab]) out[lab]=val;
        break;
      }
    }
  }
  return out;
}

function notesLower(val){
  var parts = val.split(/[,;]/).map(function(p){return p.trim();}).filter(String).slice(0,4);
  return parts.map(function(p){return p.toLowerCase();}).join(', ');
}

function slugify(s){
  s = (s||'').toLowerCase();
  var tr = {'а':'a','б':'b','в':'v','г':'h','ґ':'g','д':'d','е':'e','є':'ie','ж':'zh','з':'z',
    'и':'y','і':'i','ї':'i','й':'i','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ь':'',
    'ю':'iu','я':'ia'};
  var out='';
  for(var i=0;i<s.length;i++){ out += (tr[s[i]]!==undefined ? tr[s[i]] : s[i]); }
  return out.replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');
}

function cap(s){ return s ? s.charAt(0).toUpperCase()+s.slice(1) : s; }

function buildRows(){
  var xml = UrlFetchApp.fetch(FEED_URL, {muteHttpExceptions:true, headers:{'User-Agent':'Mozilla/5.0'}}).getContentText();
  var doc = XmlService.parse(xml);
  var ns = XmlService.getNamespace('http://base.google.com/ns/1.0');
  var items = doc.getRootElement().getChild('channel').getChildren('item');
  var rows = [];

  for(var k=0;k<items.length;k++){
    var it = items[k];
    var gid = (it.getChildText('id', ns)||'').trim();
    var rawTitle = decodeText(it.getChildText('title', ns));
    var rawDesc = it.getChildText('description', ns) || '';
    var priceRaw = it.getChildText('price', ns) || '';
    if(!gid || !rawTitle) continue;

    var isAuto = rawTitle.indexOf('Автопарфум')===0;
    var m = rawTitle.match(/(?:Авто)?[Пп]арфум\s+Vparfum\s+(.+?)\s*(\d+)\s*ml/);
    var model, volNum;
    if(m){ model=m[1].trim(); volNum=m[2]; }
    else {
      model = rawTitle.replace(/(?:Авто)?[Пп]арфум\s+Vparfum\s+/,'');
      var mv = rawTitle.match(/(\d+)\s*ml/); volNum = mv ? mv[1] : '';
    }
    var volume = volNum ? (volNum + ' мл') : '';

    var d = parseDesc(rawDesc);
    var familyRaw = d['Тип аромату'] || '';
    var familyFirst = familyRaw ? familyRaw.split(/[,;/]/)[0].trim().toLowerCase() : '';
    var familyAdj = FAMILY_ADJ[familyFirst] || familyFirst;
    var familySlug = FAMILY_SLUG[familyFirst] || (familyFirst ? slugify(familyFirst) : 'other');

    var top='';
    for(var t1=0;t1<TOP_KEYS.length;t1++){ if(d[TOP_KEYS[t1]]){ top=notesLower(d[TOP_KEYS[t1]]); break; } }

    var pm = priceRaw.match(/([\d.]+)/);
    var price = (pm ? pm[1] : '0') + ' UAH';

    var tester = (!isAuto && volNum==='10') ? ' тестер' : '';
    var head = ('Vparfum ' + model + ' ' + volume + tester).replace(/\s+/g,' ').trim().replace(/,+$/,'');
    var bits = [head];
    if(isAuto) bits.push('ароматизатор для авто Vparfum');
    else if(familyAdj) bits.push(familyAdj + ' парфум');
    else bits.push('парфум');
    if(top) bits.push(top);
    var title = bits.filter(String).join(', ').substring(0,148);

    var allNotes=[], seen={};
    for(var n=0;n<ALL_NOTE_KEYS.length;n++){
      var v=d[ALL_NOTE_KEYS[n]];
      if(v){ var lv=decodeText(v).toLowerCase(); if(!seen[lv]){ seen[lv]=1; allNotes.push(lv); } }
    }
    var notesStr = allNotes.join('; ');

    var desc, cat, ptype, grp;
    if(isAuto){
      desc = 'Автопарфум Vparfum '+model+', ароматизатор для авто, '+volume+'. '+
             (notesStr ? 'Ноти: '+notesStr+'. ' : '')+'Власне виробництво, доставка по Україні.';
      cat='2789'; ptype='Автотовари > Ароматизатори для авто'; grp='vp-'+slugify(model)+'-auto';
    } else {
      var famTxt = familyAdj ? (familyAdj+' ') : '';
      desc = (cap(famTxt)+'парфум Vparfum '+model+', '+volume+'. '+
             (notesStr ? 'Ноти: '+notesStr+'. ' : '')+'Власне виробництво, доставка по Україні.').replace(/  /g,' ');
      cat='479'; ptype = familyRaw ? ('Парфумерія > '+cap(familyRaw)+' аромати') : 'Парфумерія';
      grp='vp-'+slugify(model)+'-parfum';
    }

    var row={};
    row.id=gid; row.title=title; row.description=desc.trim(); row.price=price;
    row.google_product_category=cat; row.product_type=ptype; row.brand='Vparfum';
    row.identifier_exists='no'; row.item_group_id=grp; row.size=volume;
    row.custom_label_0 = volNum ? (volNum+'ml') : '';
    row.custom_label_1 = isAuto ? 'car_parfum' : 'personal_parfum';
    row.custom_label_2 = familySlug;
    rows.push(row);
  }
  return rows;
}

function rebuild(){
  var rows = buildRows();
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  sh.clearContents();
  var data = [COLS];
  for(var i=0;i<rows.length;i++){
    var r=rows[i], line=[];
    for(var c=0;c<COLS.length;c++){ line.push(String(r[COLS[c]]||'').replace(/[\t\n]/g,' ')); }
    data.push(line);
  }
  sh.getRange(1,1,data.length,COLS.length).setValues(data);
  SpreadsheetApp.getActiveSpreadsheet().toast(rows.length+' товарів оновлено', 'Vparfum Feed', 5);
}

function installTrigger(){
  var ts = ScriptApp.getProjectTriggers();
  for(var i=0;i<ts.length;i++){ if(ts[i].getHandlerFunction()==='rebuild') ScriptApp.deleteTrigger(ts[i]); }
  ScriptApp.newTrigger('rebuild').timeBased().everyDays(1).atHour(4).create();
  SpreadsheetApp.getActiveSpreadsheet().toast('Авто-оновлення щодня о 4:00 увімкнено', 'Vparfum Feed', 5);
}

function onOpen(){
  SpreadsheetApp.getUi().createMenu('Vparfum Feed')
    .addItem('Оновити зараз', 'rebuild')
    .addItem('Увімкнути авто-оновлення (щодня)', 'installTrigger')
    .addToUi();
}
