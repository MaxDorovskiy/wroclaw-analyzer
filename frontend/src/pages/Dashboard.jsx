import React, { useEffect, useState } from 'react'
import { api, fmtNum, fmtPln, fmtDate, fmtDateTime, fmtAgo } from '../api.js'
import { useLang, biText, roomsLabel } from '../i18n.js'
import ApiError from '../components/ApiError.jsx'

// «Огляд» — единственный экран, который отвечает на вопрос «что изменилось с
// тех пор, как я смотрел». До него система открывалась сразу таблицей с
// фильтрами: чтобы узнать новости, надо было самому вспомнить, какие фильтры
// поставить. Здесь три списка, ради которых система и собиралась (SPEC §1):
// что нового и дешевле рынка, у кого упала цена, где аренда отбивает лучше.

function Kpi({ label, value, sub, onClick, title }) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag className="card" onClick={onClick} title={title} type={onClick ? 'button' : undefined}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </Tag>
  )
}

// Короткая строка объявления: заголовок, место, цена и то число, ради которого
// объявление попало в этот список.
function Line({ l, right, onOpen, lang }) {
  return (
    <li>
      <a className="grow" href={`#/catalog?id=${l.id}`}
        onClick={e => { e.preventDefault(); onOpen(l.id) }}
        title={l.title_uk || l.title_pl || ''}>
        {l.title_uk || l.title_pl || '—'}
      </a>
      <span className="muted small" style={{ whiteSpace: 'nowrap' }}>
        {biText(lang, l.osiedle, l.osiedle_uk) || biText(lang, l.district, l.district_uk) || '—'}
        {' · '}{roomsLabel(l.rooms)} к. · {fmtNum(l.area, 0)} м²
      </span>
      <b style={{ whiteSpace: 'nowrap' }}>{fmtPln(l.price_pln)}{l.offer_type === 'rent' ? '/міс' : ''}</b>
      {right(l)}
    </li>
  )
}

function Block({ title, hint, items, loading, right, onOpen, lang, more }) {
  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 'var(--s2)' }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <span className="spacer" />
        {more}
      </div>
      {hint && <p className="hint" style={{ marginTop: 0 }}>{hint}</p>}
      {loading
        ? [0, 1, 2].map(i => <div key={i} className="skeleton sk-row" />)
        : items.length
          ? <ul className="dash-list">{items.map(l => (
              <Line key={l.id} l={l} right={right} onOpen={onOpen} lang={lang} />))}</ul>
          : <p className="muted small" style={{ margin: 0 }}>Порожньо — за цією умовою зараз нічого немає.</p>}
    </div>
  )
}

export default function Dashboard({ summary, onOpen, goTo, me }) {
  const { lang } = useLang()
  const [data, setData] = useState({ fresh: null, drops: null, yields: null })
  const [err, setErr] = useState(null)
  const isViewer = me && me.role === 'viewer'
  const kind = isViewer ? 'rent' : 'sale'

  useEffect(() => {
    let stop = false
    const get = (p) => api.listings({ per_page: 5, offer_type: kind, ...p })
      .then(d => d.items || []).catch(() => [])
    Promise.all([
      // новые за сутки: у Юлии — просто новая аренда, у владельца — новое и дешевле рынка
      get(isViewer ? { first_seen_days: 1, sort: 'first_seen', order: 'desc' }
        : { first_seen_days: 1, only_deals: 1, sort: 'discount', order: 'desc' }),
      get({ sort: 'price_drop', order: 'asc' }),
      isViewer ? Promise.resolve([]) : get({ yield_min: 6, sort: 'yield', order: 'desc' }),
    ]).then(([fresh, drops, yields]) => {
      if (!stop) setData({ fresh, drops, yields })
    }).catch(e => !stop && setErr(e))
    return () => { stop = true }
  }, [kind, isViewer])

  const s = summary || {}
  const sale = s.sale || {}
  const rent = s.rent || {}
  const tr = s.translate || {}
  const lastRun = s.last_runs && s.last_runs[kind]
  const loading = data.fresh === null

  return (
    <>
      <div className="page-head">
        <h2>Огляд</h2>
        <p>
          {isViewer
            ? 'Що зʼявилося в оренді від часу вашого останнього візиту. Зірочка додає оголошення у ваше «Обране», галочки — у підбірку для клієнта.'
            : 'Що змінилося на ринку з минулого разу: нові оголошення дешевші за медіану, знижені ціни і місця з найкращою дохідністю.'}
        </p>
      </div>

      <ApiError err={err} prefix="Огляд завантажено не повністю" />

      <div className="cards">
        <Kpi label="Активних у продажу" value={fmtNum(sale.active)}
          sub={sale.new_24h != null ? `+${fmtNum(sale.new_24h)} за добу` : null}
          onClick={() => goTo('catalog', {})} title="Перейти до каталогу продажу" />
        <Kpi label="Медіана, продаж" value={sale.median_sqm != null ? `${fmtNum(sale.median_sqm)} zł/м²` : '—'}
          sub={sale.median_price != null ? `квартира ${fmtPln(sale.median_price)}` : null}
          onClick={() => goTo('stats', {})} title="Розрізи по осиедле і дзельницях" />
        <Kpi label="Активних в оренді" value={fmtNum(rent.active)}
          sub={rent.median_rent != null ? `медіана ${fmtPln(rent.median_rent)}/міс` : null}
          onClick={() => goTo('rent', {})} title="Перейти до оренди" />
        {!isViewer && (
          <Kpi label="Вигідних зараз" value={fmtNum(sale.deals_count != null ? sale.deals_count : null)}
            sub="знижка ≥ 10% до медіани"
            onClick={() => goTo('deals', { preset: 'd10' })} title="Оголошення дешевші за схожі" />
        )}
        <Kpi label="Знято за тиждень" value={fmtNum(sale.removed_7d)}
          sub="зникли з площадок" title="Рядки не видаляються — це спостереження про ринок" />
      </div>

      <div className="dash">
        <Block
          title={isViewer ? 'Нове в оренді за добу' : 'Нові за добу і дешевші за медіану'}
          hint={isViewer ? null : 'Знижка рахується до медіани схожих квартир: те саме осиедле, кімнати, стан.'}
          items={data.fresh || []} loading={loading} onOpen={onOpen} lang={lang}
          more={<button className="btn ghost small" onClick={() => goTo(isViewer ? 'rent' : 'deals', isViewer ? {} : { preset: 'new24' })}>усі</button>}
          right={l => l.discount_pct != null && l.discount_pct >= 3
            ? <span className="badge deal">−{fmtNum(l.discount_pct, 1)}%</span>
            : <span className="muted small">{fmtDate(l.posted_at || l.first_seen)}</span>} />

        <Block
          title="Знизили ціну"
          hint="Найбільше зниження від першої побаченої нами ціни — ознака, що продавець готовий торгуватися."
          items={data.drops || []} loading={loading} onOpen={onOpen} lang={lang}
          more={<button className="btn ghost small" onClick={() => goTo(kind, { sort: 'price_drop', order: 'asc' })}>усі</button>}
          right={l => l.price_drop_pct != null && l.price_drop_pct < 0
            ? <span className="badge drop">▼ {fmtNum(Math.abs(l.price_drop_pct), 1)}%</span>
            : <span className="muted small">—</span>} />

        {!isViewer && (
          <Block
            title="Найкраща дохідність"
            hint="Валова: очікувана оренда × 12 / вкладення. Для «стану від забудовника» у вкладення входить і оздоблення."
            items={data.yields || []} loading={loading} onOpen={onOpen} lang={lang}
            more={<button className="btn ghost small" onClick={() => goTo('deals', { preset: 'y6' })}>усі</button>}
            right={l => l.yield_pct != null
              ? <span className={'badge ' + (l.yield_pct >= 6 ? 'deal' : 'gray')}>{fmtNum(l.yield_pct, 1)}%</span>
              : <span className="muted small">—</span>} />
        )}
      </div>

      {/* Состояние сбора: владельцу важно понимать, свежий ли каталог */}
      <div className="panel">
        <div className="row">
          <h3 style={{ margin: 0 }}>Стан системи</h3>
          <span className="spacer" />
          {!isViewer && <button className="btn ghost small" onClick={() => goTo('runs', {})}>Прогони</button>}
        </div>
        <div className="kv" style={{ marginBottom: 0 }}>
          <div><span className="k">Останній прогін: </span>
            {lastRun && lastRun.finished_at
              ? <>{fmtDateTime(lastRun.finished_at, { year: undefined })} <span className="muted">({fmtAgo(lastRun.finished_at)})</span></>
              : <span className="muted">ще не було</span>}
          </div>
          <div><span className="k">Оголошень побачено: </span>{lastRun ? fmtNum(lastRun.seen) : '—'}
            {lastRun && lastRun.errors > 0 && <span className="badge warn" style={{ marginLeft: 6 }}>помилок {lastRun.errors}</span>}
          </div>
          <div><span className="k">Переклад: </span>
            {tr.enabled === false
              ? <span className="badge warn">вимкнено</span>
              : <>у черзі {fmtNum((tr.pending_titles || 0) + (tr.pending_descriptions || 0))}
                {tr.running && <span className="badge gray" style={{ marginLeft: 6 }}>іде</span>}</>}
          </div>
          <div><span className="k">Курс НБП: </span>
            {s.fx && s.fx.USD ? `$ ${fmtNum(s.fx.USD, 2)} · € ${fmtNum(s.fx.EUR, 2)} zł` : '—'}</div>
        </div>
      </div>
    </>
  )
}
