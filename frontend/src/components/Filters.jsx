import React from 'react'
import MultiSelect from './MultiSelect.jsx'
import { useLang, biText, T } from '../i18n.js'

const ROOMS = ['1', '2', '3', '4+']
const CONDITION_OPTS = Object.entries(T.condition).map(([value, label]) => ({ value, label }))

// Все ключи-фильтры (без служебных sort/order/page/per_page): по ним считаем
// «Скинути · N» и по ним же чистим состояние.
export const FILTER_KEYS = [
  'rooms', 'price_min', 'price_max', 'area_min', 'area_max', 'sqm_min', 'sqm_max',
  'district', 'osiedle', 'market', 'condition', 'source', 'seller_type',
  'build_year_min', 'build_year_max', 'floor_min', 'floor_max',
  'only_deals', 'discount_min', 'yield_min', 'favorites', 'active', 'dupes', 'q',
  'first_seen_days', 'seller_key', 'has_phone',
]

// range-инпут «від / до» в общей рамке с подписью
function Range({ value, onChange, prefix, label, title, width = 74, step }) {
  return (
    <span className="range-inline" title={title}>
      <span className="lbl">{label}</span>
      <input type="number" placeholder="від" style={{ width }} step={step}
        value={value[prefix + '_min'] ?? ''}
        onChange={e => onChange(prefix + '_min', e.target.value)} />
      <input type="number" placeholder="до" style={{ width }} step={step}
        value={value[prefix + '_max'] ?? ''}
        onChange={e => onChange(prefix + '_max', e.target.value)} />
    </span>
  )
}

function Chk({ value, onChange, name, label, title }) {
  return (
    <label className="chk" title={title}>
      <input type="checkbox" checked={!!value[name]}
        onChange={e => onChange(name, e.target.checked ? 1 : null)} /> {label}
    </label>
  )
}

// rent — фильтры каталога оренди: ціна там ставка на місяць, а знижки та
// дохідності немає (їх рахуємо тільки для продажу).
export default function Filters({ value, onChange, geo, rent = false }) {
  const { lang } = useLang()
  const set = (k, v) => onChange({ ...value, [k]: v, page: 1 })

  const districts = geo?.districts || []
  const selDistricts = (value.district || '').split(',').filter(Boolean)
  const inSel = (d) => !selDistricts.length || selDistricts.includes(d)
  const countOf = (o) => rent ? o.rent_active : o.sale_active

  const districtOpts = districts.map(d => ({
    value: d.name,
    label: biText(lang, d.name, d.name_uk),
    hint: (d.osiedla || []).reduce((s, o) => s + (countOf(o) || 0), 0) || undefined,
  }))
  // осиедле сужаются выбранными дзельницами; подпись дзельницы — только когда
  // выбрано больше одной или ни одной, иначе она везде одинаковая
  const osiedleOpts = districts
    .filter(d => inSel(d.name))
    .flatMap(d => (d.osiedla || []).map(o => ({
      value: o.name,
      label: biText(lang, o.name, o.name_uk)
        + (selDistricts.length === 1 ? '' : ` — ${biText(lang, d.name, d.name_uk)}`),
      hint: countOf(o) || undefined,
    })))

  const roomsSel = (value.rooms || '').split(',').filter(Boolean)
  const toggleRoom = (r) => {
    const next = roomsSel.includes(r) ? roomsSel.filter(x => x !== r) : [...roomsSel, r]
    set('rooms', next.join(','))
  }

  const activeCount = FILTER_KEYS.filter(k => value[k] !== undefined && value[k] !== null
    && value[k] !== '' && value[k] !== false).length
  const clearAll = () => onChange({ sort: value.sort, order: value.order, page: 1, per_page: value.per_page })

  return (
    <div className="filters">
      <span style={{ display: 'flex', gap: 4 }} title="Кількість кімнат">
        {ROOMS.map(r => (
          <button key={r} type="button" className={'chip' + (roomsSel.includes(r) ? ' on' : '')}
            onClick={() => toggleRoom(r)}>{r}</button>
        ))}
      </span>
      <Range value={value} onChange={set} prefix="price"
        label={rent ? 'zł/міс' : 'ціна, zł'} width={rent ? 66 : 84}
        title={rent ? 'Ставка оренди на місяць, zł' : 'Ціна, zł'} />
      <Range value={value} onChange={set} prefix="area" label="м²" width={58}
        title="Загальна площа, м²" />
      <Range value={value} onChange={set} prefix="sqm" label="zł/м²" width={66}
        title={rent ? 'Ставка за квадратний метр на місяць' : 'Ціна за квадратний метр'} />
      <MultiSelect value={value.district} width={170}
        onChange={v => onChange({ ...value, district: v, osiedle: '', page: 1 })}
        options={districtOpts} placeholder="Дзельниця: усі" />
      <MultiSelect value={value.osiedle} width={190}
        onChange={v => set('osiedle', v)}
        options={osiedleOpts} placeholder="Осиедле: усі" />
      <select value={value.market ?? ''} onChange={e => set('market', e.target.value)}
        title="Первинний ринок — від забудовника, вторинний — від власника чи агенції">
        <option value="">Ринок: будь-який</option>
        <option value="primary">первинний</option>
        <option value="secondary">вторинний</option>
      </select>
      <MultiSelect value={value.condition} width={150}
        onChange={v => set('condition', v)}
        options={CONDITION_OPTS} placeholder="Стан: будь-який" />
      <select value={value.source ?? ''} onChange={e => set('source', e.target.value)}>
        <option value="">Джерело: усі</option>
        <option value="otodom">Otodom</option>
        <option value="olx">OLX</option>
      </select>
      <select value={value.seller_type ?? ''} onChange={e => set('seller_type', e.target.value)}>
        <option value="">Продавець: усі</option>
        <option value="private">власник</option>
        <option value="agency">агенція</option>
        <option value="developer">забудовник</option>
      </select>
      {/* «лише власники» — та же галочка, что seller_type=private в списке
          выше: для знакомой рієлторки по оренді это главный фильтр, и его
          удобнее ткнуть одним кликом, чем искать в выпадающем списке */}
      <label className="chk" title="Те саме, що «Продавець: власник» — без агенцій і забудовників">
        <input type="checkbox" checked={value.seller_type === 'private'}
          onChange={e => set('seller_type', e.target.checked ? 'private' : '')} /> лише власники
      </label>
      <Chk value={value} onChange={set} name="has_phone" label="є телефон"
        title="Лише оголошення, у яких площадка віддала телефон продавця" />
      {value.seller_key && (
        <span className="ms-chip" title={'Оголошення одного продавця: ' + value.seller_key}>
          продавець: {value.seller_key}
          <button type="button" className="ms-x" title="Показати всіх продавців"
            onClick={() => set('seller_key', '')}>×</button>
        </span>
      )}
      <Range value={value} onChange={set} prefix="build_year" label="рік" width={60}
        title="Рік будівлі" />
      <Range value={value} onChange={set} prefix="floor" label="поверх" width={50}
        title="Поверх. Нумерація польська: партер (0) = наш 1-й поверх" />
      {!rent && (
        <select value={value.discount_min ?? ''} title="Знижка до медіани zł/м² схожих квартир"
          onChange={e => set('discount_min', e.target.value === '' ? null : +e.target.value)}>
          <option value="">Знижка: будь-яка</option>
          <option value="5">≥ 5%</option>
          <option value="10">≥ 10%</option>
          <option value="15">≥ 15%</option>
          <option value="20">≥ 20%</option>
        </select>
      )}
      {!rent && (
        <select value={value.yield_min ?? ''}
          title="Валова дохідність від оренди: очікувана ставка × 12 / вкладення. Без оголошень оренди поруч цифри немає"
          onChange={e => set('yield_min', e.target.value === '' ? null : +e.target.value)}>
          <option value="">Дохідність: будь-яка</option>
          <option value="4">≥ 4% річних</option>
          <option value="5">≥ 5% річних</option>
          <option value="6">≥ 6% річних</option>
          <option value="7">≥ 7% річних</option>
          <option value="8">≥ 8% річних</option>
        </select>
      )}
      <select value={value.active ?? ''} onChange={e => set('active', e.target.value)}
        title="Зняті оголошення лишаються в базі й беруть участь у медіанах, але типово не показуються">
        <option value="">лише активні</option>
        <option value="0">активні + зняті</option>
      </select>
      <Chk value={value} onChange={set} name="favorites" label="★ обрані" />
      <Chk value={value} onChange={set} name="dupes" label="показувати всі розміщення (дублі)"
        title="Типово одна квартира — один рядок (найдешевше активне розміщення); решта розміщень — у картці" />
      <input type="text" placeholder="Пошук: заголовок, вулиця…" style={{ minWidth: 200 }}
        value={value.q ?? ''} onChange={e => set('q', e.target.value)} />
      {activeCount > 0 && (
        <button type="button" className="btn danger" style={{ padding: '6px 12px' }}
          title="Скинути всі фільтри" onClick={clearAll}>
          ✕ Скинути · {activeCount}
        </button>
      )}
    </div>
  )
}
