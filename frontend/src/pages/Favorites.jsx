import React, { useEffect, useState } from 'react'
import { api, fmtNum } from '../api.js'
import Catalog from './Catalog.jsx'

// Обране кожного логіна окреме: зірочка завжди додає в СВІЙ список.
// Власник може подивитись список Юлії (вона його — ні, сервер відповість 403);
// зірочка при цьому лишається своя, тож знахідку Юлії можна забрати собі.
const SORTS = [['fav', 'за датою додавання'], ['posted', 'за датою подачі']]

export default function Favorites({ onOpen, geo, urlParams, onParams, me, sel, onSel }) {
  const [users, setUsers] = useState(null)
  const [who, setWho] = useState((urlParams && urlParams.fav_user) || '')
  const isAdmin = me && me.role === 'admin'

  useEffect(() => { api.favoriteUsers().then(setUsers).catch(() => setUsers(null)) }, [])

  const mine = !who || who === (me && me.user)
  const count = (u) => {
    const row = users && users.users.find(x => x.user === u)
    return row ? row.count : null
  }
  const total = count(who || (me && me.user))

  const toolbar = (
    <div className="panel row" style={{ alignItems: 'center', gap: 12 }}>
      <h3 style={{ margin: 0 }}>★ Обране{total != null ? <span className="muted"> · {fmtNum(total)}</span> : null}</h3>
      {isAdmin && users && users.users.length > 1 && (
        <label className="chk">чиє:
          <select value={who} onChange={e => setWho(e.target.value)}>
            {users.users.map(u => (
              <option key={u.user} value={u.user === me.user ? '' : u.user}>
                {u.user === me.user ? 'моє' : u.user} ({u.count})
              </option>
            ))}
          </select>
        </label>
      )}
      <span className="muted small">
        {mine
          ? 'Зірочка в каталозі додає сюди. Список у кожного свій — Юлія ваш не бачить.'
          : `Список ${who}. Зірочка тут додає оголошення у ВАШЕ обране.`}
      </span>
    </div>
  )

  // Чьё обране показываем — решает ЭТОТ переключатель, а не адрес: иначе
  // fav_user из адреса пересилил бы пресет, и возврат к «моє» не срабатывал.
  // В адрес значение всё равно попадёт (каталог пишет туда свои фильтры),
  // поэтому ссылкой на чужой список поделиться можно.
  const rest = { ...(urlParams || {}) }
  delete rest.fav_user

  return (
    // key — чтобы смена «чиє» перемонтировала каталог с новым пресетом;
    // пустая строка ключом не годится, отсюда 'me'
    <Catalog key={who || 'me'} onOpen={onOpen} geo={geo} offerType="all" extraSorts={SORTS}
      sel={sel} onSel={onSel} urlParams={rest} onParams={onParams} toolbar={toolbar}
      preset={{ favorites: 1, fav_user: who || undefined, sort: 'fav', order: 'desc' }} />
  )
}
