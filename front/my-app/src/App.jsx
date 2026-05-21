import React, { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'

const API = import.meta.env.VITE_API_URL ?? ''
const PAGE_SIZE = 50

function loadAuth() {
  try {
    const raw = localStorage.getItem('redcat_auth')
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}
function CustomSelect({ value, onChange, options }) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const selectedLabel = options.find(o => String(o.value) === String(value))?.label || value;
  const filteredOptions = options.filter((opt) =>
    String(opt.label || opt.value || '').toLowerCase().includes(search.trim().toLowerCase())
  )

  const toggleOpen = () => {
    setIsOpen((current) => {
      if (!current) setSearch('')
      return !current
    })
  }

  return (
    <div className="custom-select">
      <div className="select-trigger" onClick={toggleOpen}>
        {selectedLabel}
      </div>

      {isOpen && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={() => setIsOpen(false)} />
          <div className="select-options">
            <input
              className="select-search"
              placeholder="Поиск"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onClick={(event) => event.stopPropagation()}
            />
            <div className="select-options-list">
              {filteredOptions.length ? filteredOptions.map((opt) => (
                <div
                  key={opt.value}
                  className={`select-option ${value === opt.value ? 'active' : ''}`}
                  onClick={() => {
                    onChange(opt.value);
                    setIsOpen(false);
                  }}
                >
                  {opt.label}
                </div>
              )) : (
                <div className="select-empty">Ничего не найдено</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function MultiSelect({ values, onChange, options, placeholder }) {
  const [isOpen, setIsOpen] = React.useState(false)
  const [search, setSearch] = React.useState('')
  const selected = Array.isArray(values) ? values : []
  const selectedLabels = options
    .filter((option) => selected.includes(String(option.value)))
    .map((option) => option.label)
  const label = selectedLabels.length ? selectedLabels.join(', ') : placeholder
  const filteredOptions = options.filter((opt) =>
    String(opt.label || opt.value || '').toLowerCase().includes(search.trim().toLowerCase())
  )

  const toggleOpen = () => {
    setIsOpen((current) => {
      if (!current) setSearch('')
      return !current
    })
  }

  const toggleValue = (value) => {
    const text = String(value)
    onChange(selected.includes(text)
      ? selected.filter((item) => item !== text)
      : [...selected, text])
  }

  return (
    <div className="custom-select multi-select">
      <div className="select-trigger" onClick={toggleOpen}>
        {label}
      </div>

      {isOpen && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={() => setIsOpen(false)} />
          <div className="select-options">
            <input
              className="select-search"
              placeholder="Поиск"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onClick={(event) => event.stopPropagation()}
            />
            <div className="select-options-list">
              <div
                className={`select-option ${selected.length === 0 ? 'active' : ''}`}
                onClick={() => onChange([])}
              >
                {placeholder}
              </div>
              {filteredOptions.length ? filteredOptions.map((opt) => (
                <div
                  key={opt.value}
                  className={`select-option ${selected.includes(String(opt.value)) ? 'active' : ''}`}
                  onClick={() => toggleValue(opt.value)}
                >
                  {opt.label}
                </div>
              )) : (
                <div className="select-empty">Ничего не найдено</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function routeUrl(path) {
  return `${window.location.origin}${window.location.pathname}#${path}`
}

function openExternalTab(url) {
  const opened = window.open(url, '_blank')
  if (opened) opened.opener = null
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('ru-RU', {
    timeZone: 'Europe/Moscow',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function signalTime(item) {
  const value = item?.published_at || item?.created_at
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

function compactDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('ru-RU', {
    timeZone: 'Europe/Moscow',
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function planLabel(plan) {
  const labels = {
    demo: 'Демо-доступ',
    basic: 'Basic',
    plus: 'Plus',
    manager: 'Manager',
  }
  return labels[plan] || 'Без подписки'
}

function subscriptionStatusLabel(status) {
  const labels = {
    active: 'Активна',
    inactive: 'Не активирована',
    expired: 'Истекла',
  }
  return labels[status] || status || 'Не активирована'
}

function hotnessClass(value) {
  return `hotness-${Number(value) || 0}`
}

function categoryClass(category) {
  const value = String(category || '').toLowerCase()

  if (value.includes('регулирование') || value.includes('комплаенс')) return 'category-regulation'
  if (value.includes('платеж') || value.includes('инфраструктур')) return 'category-payments'
  if (value.includes('антифрод') || value.includes('кибер')) return 'category-antifraud'
  if (value.includes('продукт') || value.includes('клиент')) return 'category-products'
  if (value.includes('конкурент') || value.includes('банковский рынок')) return 'category-competitors'
  if (value.includes('финтех') || value.includes('технолог')) return 'category-tech'
  if (value.includes('идентифика') || value.includes('биометр')) return 'category-identity'
  if (value.includes('санкц') || value.includes('огранич')) return 'category-sanctions'
  if (value.includes('макро') || value.includes('ставк')) return 'category-macro'
  if (value.includes('рынки') || value.includes('инвест')) return 'category-market'
  if (value.includes('результат') || value.includes('отчет')) return 'category-reporting'
  if (value.includes('статист') || value.includes('данн')) return 'category-stats'
  if (value.includes('банк') || value.includes('bank')) return 'category-banking'
  return 'category-default'
}

async function apiFetch(path, options = {}, token = '') {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API}${path}`, {
    ...options,
    headers,
  })

  let data = {}
  try {
    data = await response.json()
  } catch {
    data = {}
  }

  if (!response.ok) {
    const error = new Error(data.error || data.message || data.update?.message || 'Что-то пошло не так')
    error.data = data
    error.status = response.status
    throw error
  }

  return data
}

function updateMessage(data) {
  const status = String(data?.update?.status || data?.status || '').toLowerCase()
  const message = String(data?.update?.message || data?.message || '').toLowerCase()
  if (status === 'busy' || message.includes('already running')) {
    return 'Поиск уже идёт'
  }
  if (status === 'rate_limited' || message.includes('once every') || message.includes('recent')) {
    return 'Поиск был произведён недавно'
  }
  return 'Поиск начат, время обновления займёт до 30 минут'
}

function updateErrorMessage(error) {
  const message = String(error?.message || '').toLowerCase()
  if (message.includes('missing authorization') || message.includes('unauthorized')) {
    return 'Только для авторизованных пользователей'
  }
  if (message.includes('already running')) return 'Поиск уже идёт'
  if (message.includes('once every') || message.includes('recent')) return 'Поиск был произведён недавно'
  return error.message
}

async function copySignalLink(signalId) {
  const url = routeUrl(`/signals/${signalId}`)
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url)
    } else {
      window.prompt('Ссылка на новость', url)
    }
  } catch {
    window.prompt('Ссылка на новость', url)
  }
  window.dispatchEvent(new CustomEvent('redcat:flash', { detail: 'Ссылка скопирована' }))
}

function Market({ market }) {
  const [items, setItems] = useState(Array.isArray(market) ? market : (market?.items || []))
  const [hasMore, setHasMore] = useState(Boolean(market?.has_more))
  const [loading, setLoading] = useState(false)
  const [snapshot, setSnapshot] = useState(market?.snapshot)
  const [events, setEvents] = useState(market?.events || [])
  const [archivedEvents, setArchivedEvents] = useState(market?.archived_events || [])
  const [showArchivedEvents, setShowArchivedEvents] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState('value_desc')
  const [movement, setMovement] = useState('all')
  const [error, setError] = useState('')

  useEffect(() => {
    setItems(Array.isArray(market) ? market : (market?.items || []))
    setHasMore(Boolean(market?.has_more))
    setSnapshot(market?.snapshot)
    setEvents(market?.events || [])
    setArchivedEvents(market?.archived_events || [])
  }, [market])

  const buildMarketPath = (offset) => {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
      sort: sortBy,
      movement,
    })
    if (query.trim()) params.set('q', query.trim())
    return `/api/market?${params.toString()}`
  }

  const loadMarket = async (reset = false) => {
    const offset = reset ? 0 : items.length
    setLoading(true)
    setError('')
    if (reset) {
      setItems([])
      setHasMore(false)
    }
    try {
      const data = await apiFetch(buildMarketPath(offset))
      setItems((prev) => reset ? (data.items || []) : [...prev, ...(data.items || [])])
      setHasMore(Boolean(data.has_more))
      setSnapshot(data.snapshot)
      setEvents(data.events || [])
      setArchivedEvents(data.archived_events || [])
    } catch (loadError) {
      setError(loadError.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    setItems([])
    setHasMore(false)
    ;(async () => {
      try {
        const data = await apiFetch(buildMarketPath(0))
        if (!alive) return
        setItems(data.items || [])
        setHasMore(Boolean(data.has_more))
        setSnapshot(data.snapshot)
        setEvents(data.events || [])
        setArchivedEvents(data.archived_events || [])
        setShowArchivedEvents(false)
      } catch (loadError) {
        if (alive) setError(loadError.message)
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [query, sortBy, movement])

  const submitSearch = (event) => {
    event.preventDefault()
    setQuery(searchInput.trim())
  }

  return (
    <div className="page">
      <section className="card page-head">
        <h1>MOEX</h1>
        <p>Актуальный срез MOEX ISS: цена, изменение, оборот, сделки и рыночные события.</p>
      </section>

      {snapshot ? (
        <section className="card moex-snapshot">
          <div className="section-head">
            <div>
              <h2>Рыночный снимок</h2>
              <p className="muted">Последний доступный срез торговой сессии: {snapshot.trade_date || '—'} · обновлено {compactDate(snapshot.fetched_at)}</p>
            </div>
          </div>
          <div className="moex-kpi-grid">
            <div className="moex-kpi">
              <span>Оборот, ₽</span>
              <strong>{formatNumber(snapshot.total_value)}</strong>
              <small>{snapshot.top_value_ticker || '—'} · {formatNumber(snapshot.top_value)}</small>
            </div>
            <div className="moex-kpi">
              <span>Сделок</span>
              <strong>{formatNumber(snapshot.total_trades)}</strong>
              <small>{snapshot.most_traded_ticker || '—'} · {formatNumber(snapshot.most_traded_count)}</small>
            </div>
            <div className="moex-kpi">
              <span>Лидер роста</span>
              <strong>{snapshot.leader_gain_ticker || '—'} {formatPercent(snapshot.leader_gain_percent)}</strong>
              <small>лучшее движение дня</small>
            </div>
            <div className="moex-kpi">
              <span>Лидер снижения</span>
              <strong>{snapshot.leader_drop_ticker || '—'} {formatPercent(snapshot.leader_drop_percent)}</strong>
              <small>худшее движение дня</small>
            </div>
          </div>
        </section>
      ) : null}

      <section className="card moex-events">
        <div className="section-head">
          <div>
            <h2>Рыночные события</h2>
            <p className="muted">Критерии: оборот или число сделок в 3+ раза выше медианы за 30 торговых дней; либо цена изменилась на 3%+ за день.</p>
          </div>
        </div>
        {events.length ? (
          <div className="moex-event-list">
            {events.map((event, idx) => (
              <div key={idx} className="moex-event">
                <div className="moex-event-head">
                  <strong>{event.title}</strong>
                </div>
                {event.description ? <p>{event.description}</p> : null}
                {event.related_tickers?.length ? <small>Тикеры: {event.related_tickers.join(', ')}</small> : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <p className="muted">Сильных рыночных событий не найдено.</p>
          </div>
        )}
        {archivedEvents.length ? (
          <div className="moex-archive-block">
            <button className="button ghost" onClick={() => setShowArchivedEvents((value) => !value)}>
              {showArchivedEvents ? 'Скрыть предыдущие дни' : 'Показать предыдущие 3 торговых дня'}
            </button>
            {showArchivedEvents ? (
              <div className="moex-event-list moex-archive-list">
                {archivedEvents.map((event, idx) => (
                  <div key={`${event.event_date}-${idx}`} className="moex-event is-archived">
                    <div className="moex-event-head">
                      <strong>{event.title}</strong>
                    </div>
                    <small className="moex-event-date">{event.event_date || event.date || 'прошлая дата'}</small>
                    {event.description ? <p>{event.description}</p> : null}
                    {event.related_tickers?.length ? <small>Тикеры: {event.related_tickers.join(', ')}</small> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="card moex-table-card">
        <div className="section-head">
          <div>
            <h2>Торги</h2>
            <p className="muted">Поиск работает по тикеру и названию инструмента за последнюю доступную торговую дату.</p>
          </div>
        </div>
        <form className="search-form moex-search-form" onSubmit={submitSearch}>
          <input
            className="search-input"
            placeholder="Поиск по тикеру или названию. Нажмите Enter для запуска."
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
          <button className="button ghost" type="submit" disabled={loading}>
            Найти
          </button>
        </form>
        <div className="cards-toolbar moex-toolbar">
          <CustomSelect
            value={sortBy}
            onChange={setSortBy}
            options={[
              { value: 'value_desc', label: 'По обороту' },
              { value: 'trades_desc', label: 'По сделкам' },
              { value: 'change_desc', label: 'Сильнее рост' },
              { value: 'change_asc', label: 'Сильнее падение' },
              { value: 'price_desc', label: 'По цене' },
              { value: 'ticker_asc', label: 'По тикеру' }
            ]}
          />
          <CustomSelect
            value={movement}
            onChange={setMovement}
            options={[
              { value: 'all', label: 'Все инструменты' },
              { value: 'active', label: 'Только с торгами' },
              { value: 'gainers', label: 'Только рост' },
              { value: 'losers', label: 'Только падение' },
              { value: 'strong', label: 'Движение 3%+' }
            ]}
          />
        </div>
        {error ? (
          <div className="empty-state">
            <p className="muted">{error}</p>
          </div>
        ) : null}
          {items.length ? (
            <div className="table-scroll">
            <table className="market-table moex-table">
              <thead>
                <tr>
                  <th>Тикер</th>
                  <th>Название</th>
                  <th>Цена</th>
                  <th>Изм.</th>
                  <th>Оборот, ₽</th>
                  <th>Сделок</th>
                  <th>Объём</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => (
                  <tr key={`${item.secid}-${item.boardid}-${index}`}>
                    <td><strong>{item.secid}</strong></td>
                    <td>
                      <div>{item.shortname || item.secname || '—'}</div>
                      {item.secname && item.secname !== item.shortname ? <small className="muted">{item.secname}</small> : null}
                    </td>
                    <td>{formatNumber(item.last ?? item.marketprice, 2)}</td>
                    <td className={Number(item.change_percent) >= 0 ? 'moex-positive' : 'moex-negative'}>
                      {formatPercent(item.change_percent)}
                    </td>
                    <td>{formatNumber(item.value_rub)}</td>
                    <td>{formatNumber(item.trades)}</td>
                    <td>{formatNumber(item.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          ) : (
            <div className="empty-state">
              <p className="muted">{loading ? 'Пожалуйста подождите, данные загружаются.' : 'Данные не найдены в базе.'}</p>
            </div>
          )}
      </section>

      {hasMore ? (
        <div className="load-more-row">
          <button className="button ghost" onClick={() => loadMarket(false)} disabled={loading}>
            {loading ? 'Загрузка...' : `Загрузить ещё ${PAGE_SIZE}`}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function formatNumber(value, decimals = 0) {
  if (!value && value !== 0) return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (Number.isNaN(num)) return '—'
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  }).format(num)
}

function formatPercent(value) {
  if (!value && value !== 0) return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (Number.isNaN(num)) return '—'
  return `${num > 0 ? '+' : ''}${formatNumber(num, 2)}%`
}

// Компонент для защиты путей
function ProtectedRoute({ auth, children }) {
  if (!auth) {
    // Если не авторизован — редирект на логин (или на главную с алертом)
    return <Navigate to="/login" replace />;
  }
  if (!auth.user?.activated) {
    return <Navigate to={`/activate?email=${encodeURIComponent(auth.user?.email || '')}`} replace />;
  }
  return children;
}

// Продвинутый парсер доменов (Пункт 5)
const getDomain = (url) => {
  if (!url) return 'источник';
  try {
    let clean = url.trim();
    if (!/^https?:\/\//i.test(clean)) clean = 'https://' + clean;
    const host = new URL(clean).hostname;
    return host.replace(/^www\./i, '');
  } catch (e) {
    return url;
  }
};

function sourceLabel(source, fallback = '') {
  const url = typeof source === 'string' ? source : source?.url
  const name = typeof source === 'object' ? source?.name : ''
  const domain = getDomain(url || '')
  const cleanedName = String(name || fallback || '').replace(/^Telegram:\s*/i, '').trim()

  if (domain === 't.me' || domain.endsWith('.t.me')) {
    if (cleanedName) return `Tg: ${cleanedName}`
    try {
      const parsed = new URL(/^https?:\/\//i.test(url) ? url : `https://${url}`)
      const channel = parsed.pathname.split('/').filter(Boolean)[0]
      return channel ? `Tg: @${channel}` : 'Tg: Telegram'
    } catch {
      return cleanedName ? `Tg: ${cleanedName}` : 'Tg: Telegram'
    }
  }

  return domain || cleanedName || 'Источник'
}

function SourceLinks({ item, compact = false }) {
  const links = Array.isArray(item.source_links) && item.source_links.length
    ? item.source_links.filter((source) => source?.url || source?.name)
    : []
  const urls = !links.length && Array.isArray(item.source_urls) && item.source_urls.length
    ? item.source_urls.filter(Boolean)
    : []

  if (!links.length && !urls.length) {
    const names = Array.isArray(item.sources) && item.sources.length ? item.sources : [item.source_name].filter(Boolean)
    return names.length ? (
      <div className={`source-links ${compact ? 'compact' : ''}`}>
        {names.map((name) => <span key={name} className="source-link muted-source">{name}</span>)}
      </div>
    ) : null
  }

  const normalizedLinks = links.length
    ? links
    : urls.map((url, idx) => ({ url, name: Array.isArray(item.sources) ? item.sources[idx] : item.source_name }))

  return (
    <div className={`source-links ${compact ? 'compact' : ''}`}>
      {normalizedLinks.map((source, idx) => (
        <a
          key={`${source.url || source.name}-${idx}`}
          href={source.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          className="source-link"
          title={source.name ? `${source.name}: ${source.url}` : source.url}
          onClick={(event) => event.stopPropagation()}
        >
          {sourceLabel(source)}
        </a>
      ))}
    </div>
  )
}

export default function App() {
  const [auth, setAuth] = useState(loadAuth())
  const [signals, setSignals] = useState([])
  const [market, setMarket] = useState([])
  const [overview, setOverview] = useState({})
  const [favorites, setFavorites] = useState([])
  const [notifications, setNotifications] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [settings, setSettings] = useState([])
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [messageClosing, setMessageClosing] = useState(false)
  const [updating, setUpdating] = useState(false)

  const persistAuth = (payload) => {
    const next = { token: payload.token, user: payload.user }
    localStorage.setItem('redcat_auth', JSON.stringify(next))
    setAuth(next)
  }

  const logout = () => {
    localStorage.removeItem('redcat_auth')
    setAuth(null)
    setFavorites([])
    setNotifications([])
    setUnreadCount(0)
    setSettings([])
    setUsers([])
  }

  const refreshSignals = async () => {
    const data = await apiFetch(`/api/signals?limit=${PAGE_SIZE}`)
    setSignals(data.items || [])
  }

  const refreshMarket = async () => {
    const data = await apiFetch(`/api/market?limit=${PAGE_SIZE}`)
    setMarket(data)
  }

  const refreshOverview = async () => {
    const data = await apiFetch('/api/overview')
    setOverview(data || {})
  }

  const refreshSession = async (token = auth?.token) => {
    if (!token) return
    const [me, favs, notif, prefs] = await Promise.all([
      apiFetch('/api/me', {}, token),
      apiFetch('/api/favorites', {}, token),
      apiFetch('/api/notifications', {}, token),
      apiFetch('/api/notification-settings', {}, token),
    ])

    const nextAuth = { token, user: me.user }
    localStorage.setItem('redcat_auth', JSON.stringify(nextAuth))
    setAuth(nextAuth)
    setFavorites(favs.items || [])
    setNotifications(notif.items || [])
    setUnreadCount(notif.unread_count || 0)
    setSettings(prefs.items || [])
  }

  const refreshAdmin = async (token = auth?.token) => {
    if (!token) return
    const usersData = await apiFetch('/api/admin/users', {}, token)
    setUsers(usersData.items || [])
  }

  const loadAll = async () => {
    await Promise.all([refreshSignals(), refreshMarket(), refreshOverview()])
    if (auth?.token) {
      await refreshSession(auth.token)
      if (auth?.user?.role === 'admin') {
        await refreshAdmin(auth.token)
      }
    }
  }

  const runUpdate = async () => {
    if (!auth?.token) {
      flash('Только для авторизованных пользователей')
      return
    }

    setUpdating(true)
    try {
      const data = await apiFetch('/api/update', {
        method: 'POST',
        body: JSON.stringify({}),
      }, auth?.token)
      flash(updateMessage(data))
      await refreshOverview()
    } catch (error) {
      flash(updateErrorMessage(error))
    } finally {
      setUpdating(false)
    }
  }

  useEffect(() => {
    let alive = true

    ;(async () => {
      try {
        await loadAll()
      } catch (error) {
        if (alive) setMessage(error.message)
      } finally {
        if (alive) setLoading(false)
      }
    })()

    return () => {
      alive = false
    }
  }, [auth?.token])

  const flash = (text) => {
    setMessageClosing(false)
    setMessage(text)
    window.clearTimeout(window.__redcatFlashTimer)
    window.clearTimeout(window.__redcatFlashCloseTimer)
    window.__redcatFlashTimer = window.setTimeout(() => setMessageClosing(true), 2300)
    window.__redcatFlashCloseTimer = window.setTimeout(() => {
      setMessage('')
      setMessageClosing(false)
    }, 2700)
  }

  useEffect(() => {
    const handler = (event) => flash(event.detail || 'Готово')
    window.addEventListener('redcat:flash', handler)
    return () => window.removeEventListener('redcat:flash', handler)
  }, [])

  const saveProfile = async (payload) => {
    const data = await apiFetch('/api/me', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }, auth.token)

    const next = { token: auth.token, user: data.user }
    localStorage.setItem('redcat_auth', JSON.stringify(next))
    setAuth(next)
    setMessage('Профиль сохранён')
    await refreshSession(auth.token)
  }

  const toggleFavorite = async (signalId) => {
    if (!auth?.token) {
      flash('Сначала войди в аккаунт')
      return
    }

    await apiFetch(`/api/signals/${signalId}/favorite`, {
      method: 'POST',
      body: JSON.stringify({}),
    }, auth.token)

    await refreshSession(auth.token)
  }

  const saveNotificationSettings = async (rules) => {
    if (!auth?.token) return
    await apiFetch('/api/notification-settings', {
      method: 'PUT',
      body: JSON.stringify({ rules }),
    }, auth.token)
    await refreshSession(auth.token)
  }

  const clearNotifications = async () => {
    if (!auth?.token) return
    await apiFetch('/api/notifications/clear', { method: 'DELETE' }, auth.token)
    await refreshSession(auth.token)
  }

  const markNotificationRead = async (notificationId) => {
    if (!auth?.token || !notificationId) return
    await apiFetch(`/api/notifications/${notificationId}/read`, {
      method: 'POST',
      body: JSON.stringify({}),
    }, auth.token)
    await refreshSession(auth.token)
  }

  const rebuildNotifications = async () => {
    if (!auth?.token) return
    await apiFetch('/api/notifications/rebuild', {
      method: 'POST',
      body: JSON.stringify({}),
    }, auth.token)
    await refreshSession(auth.token)
  }

  const signalCardList = useMemo(() => signals || [], [signals])

  if (loading) {
    return (
      <div className="app-shell">
        <TopBar auth={auth} onLogout={logout} />
        <main className="page-wrap">
          <div className="card center-card">
            <h2>Загружаем данные</h2>
            <p>Подтягиваю сигналы, MOEX и настройки из базы.</p>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <TopBar auth={auth} onLogout={logout} unreadCount={unreadCount} />

      {message ? <div className={`top-message ${messageClosing ? 'closing' : ''}`}>{message}</div> : null}

     <main className="page-wrap">
  <Routes>
    {/* Открытые страницы */}
    <Route path="/" element={<HomePage signals={signalCardList} overview={overview} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} onRunUpdate={runUpdate} updating={updating} />} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="/digests" element={<DigestsPage />} />
    <Route path="/register" element={auth ? <Navigate to="/account" replace /> : <RegisterPage onAuth={persistAuth} />} />
    <Route path="/login" element={auth ? <Navigate to="/account" replace /> : <LoginPage onAuth={persistAuth} />} />
    <Route path="/activate" element={<ActivationPage onAuth={persistAuth} auth={auth} />} />

    {/* Защищенные страницы (только для авторизованных) */}
    <Route path="/cards" element={
      <ProtectedRoute auth={auth}>
        <CardsPage signals={signalCardList} overview={overview} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} />
      </ProtectedRoute>
    } />
    <Route path="/signals/:id" element={
      <ProtectedRoute auth={auth}>
        <SignalDetailPage signals={signalCardList} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} />
      </ProtectedRoute>
    } />
    <Route path="/moex" element={
      <ProtectedRoute auth={auth}><Market market={market} /></ProtectedRoute>
    } />
    <Route path="/notifications" element={
      <ProtectedRoute auth={auth}>
        <NotificationsPage auth={auth} overview={overview} notifications={notifications} settings={settings} onSaveSettings={saveNotificationSettings} onClear={clearNotifications} onRead={markNotificationRead} />
      </ProtectedRoute>
    } />
    <Route path="/saved" element={
      <ProtectedRoute auth={auth}>
        <SavedPage auth={auth} favorites={favorites} onToggleFavorite={toggleFavorite} />
      </ProtectedRoute>
    } />
    <Route path="/account" element={
      <ProtectedRoute auth={auth}><AccountPage auth={auth} onSaveProfile={saveProfile} /></ProtectedRoute>
    } />

    <Route path="/admin/users" element={
      <RequireAdmin auth={auth}><AdminUsersPage auth={auth} users={users} refreshAdmin={refreshAdmin} /></RequireAdmin>
    } />
    <Route path="/admin/subscriptions" element={
      <Navigate to="/admin/users" replace />
    } />

    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
      </main>

      <Footer />
    </div>
  )
}

function StarNavIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="nav-svg">
      <path d="M12 3.4l2.6 5.26 5.8.84-4.2 4.1.99 5.78L12 16.65 6.81 19.38l.99-5.78-4.2-4.1 5.8-.84L12 3.4z" />
    </svg>
  )
}

function BellNavIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="nav-svg">
      <path d="M12 22a2.6 2.6 0 0 0 2.5-1.9h-5A2.6 2.6 0 0 0 12 22zm7-5.2-1.7-1.7V10a5.3 5.3 0 0 0-4.1-5.2V3.7a1.2 1.2 0 0 0-2.4 0v1.1A5.3 5.3 0 0 0 6.7 10v5.1L5 16.8v1.1h14v-1.1z" />
    </svg>
  )
}

function TopBar({ auth, onLogout, unreadCount = 0 }) {
  const [open, setOpen] = useState(false)

  const links = [
    ['/', 'Главная'],
    ['/about', 'О проекте'],
    ['/digests', 'Дайджесты'],
    ['/cards', 'FinTech News'],
    ['/moex', 'MOEX'],
  ]

  const isAdmin = auth?.user?.role === 'admin'

  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <img src="/logoRedCat.png" alt="Red Cat" />
        <div>
          <div className="brand-title">Red Cat</div>
          <div className="brand-subtitle">TrendWatcher</div>
        </div>
      </Link>

      <nav className="nav">
        {links.map(([rawTo, rawLabel]) => {
          const to = rawTo
          const label = rawLabel
          return (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            <span>{label}</span>
          </NavLink>
          )
        })}

        {auth ? (
          <>
          <NavLink
            to="/saved"
            title="Избранное"
            aria-label="Избранное"
            className={({ isActive }) => `nav-link nav-icon-link ${isActive ? 'active' : ''}`}
          >
            <StarNavIcon />
          </NavLink>
          <NavLink
            to="/notifications"
            title="Уведомления"
            aria-label="Уведомления"
            className={({ isActive }) => `nav-link nav-icon-link ${isActive ? 'active' : ''}`}
          >
            <BellNavIcon />
            {unreadCount ? <span className="nav-unread-dot" /> : null}
          </NavLink>
          {isAdmin ? (
            <NavLink to="/admin/users" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              Пользователи
            </NavLink>
          ) : null}
          <div className="account-dropdown" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
            <NavLink to="/account" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              {auth.user?.full_name || auth.user?.email || 'Профиль'}
            </NavLink>
            {open ? (
              <div className="dropdown-menu">
                <NavLink to="/account" className="dropdown-item">Аккаунт</NavLink>
                <button onClick={onLogout}>Выйти</button>
              </div>
            ) : null}
          </div>
          </>
        ) : (
          <>
            <NavLink to="/login" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Вход</NavLink>
            <NavLink to="/register" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Регистрация</NavLink>
          </>
        )}
      </nav>
    </header>
  )
}

function Footer() {
  return (
    <footer className="footer">
      <span>Red Cat Trendwatcher</span>
      <span>React + Flask + SQLAlchemy</span>
    </footer>
  )
}

function ToastBar({ item, onClose }) {
  const navigate = useNavigate()

  const open = () => {
    if (item.signal_id) {
      navigate(`/signals/${item.signal_id}`)
    } else {
      navigate('/notifications')
    }
    onClose()
  }

  return (
    <button className="toast-bar" onClick={open}>
      <span>{item.title}</span>
      <span className="toast-close" onClick={(e) => { e.stopPropagation(); onClose() }}>×</span>
    </button>
  )
}

function HomePage({ signals, overview = {}, favorites = [], auth, onToggleFavorite, onRunUpdate, updating }) {
  const [pyramidItems, setPyramidItems] = useState(null)

  const filteredSignals = useMemo(() =>
    signals.filter(s => Number(s.hotness) > 1),
    [signals]
  );

  const sorted = useMemo(
    () => [...filteredSignals].sort((a, b) => signalTime(b) - signalTime(a)),
    [filteredSignals],
  )

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [h5, h4, h3] = await Promise.all([
          apiFetch('/api/signals?limit=1&hotness=5&sort=time_desc'),
          apiFetch('/api/signals?limit=2&hotness=4&sort=time_desc'),
          apiFetch('/api/signals?limit=3&hotness=3&sort=time_desc'),
        ])
        if (alive) {
          setPyramidItems({
            hot5: h5.items || [],
            hot4: h4.items || [],
            hot3: h3.items || [],
          })
        }
      } catch {
        if (alive) setPyramidItems(null)
      }
    })()
    return () => {
      alive = false
    }
  }, [signals.length])

  const hot5 = pyramidItems?.hot5 || sorted.filter((item) => Number(item.hotness) === 5).slice(0, 1)
  const hot4 = pyramidItems?.hot4 || sorted.filter((item) => Number(item.hotness) === 4).slice(0, 2)
  const hot3 = pyramidItems?.hot3 || sorted.filter((item) => Number(item.hotness) === 3).slice(0, 3)

  const counts = {
    observations: overview.observations ?? signals.length,
    processedLastWeek: overview.processed_last_7d ?? 0,
    sources: overview.sources ?? new Set(signals.map((item) => item.source_name).filter(Boolean)).size,
    processedLastDay: overview.processed_last_24h ?? 0,
    lastParsed: compactDate(overview.last_parsed_at),
    lastUpdate: compactDate(overview.last_update_at),
  }

  return (
    <div className="stack">
      <section className="hero card">
        <div className="hero-copy">
          <h1>Опережай тренды. Управляй будущим.</h1>
          <p>Сервис мониторит финтех-новости, банковский рынок и регуляторные изменения, превращая поток публикаций в понятные аналитические карточки.</p>
          <div className="hero-actions">
            <Link to="/cards" className="button primary">Открыть FinTech News</Link>
            {auth && auth.user?.role !== 'admin' && auth.user?.subscription_status === 'active' ? (
              <button className="button ghost" onClick={onRunUpdate} disabled={updating}>
                {updating ? 'Запускаю...' : 'Обновить базу'}
              </button>
            ) : null}
          </div>
        </div>

        <div className="hero-panel">
          <div className="kpi-grid">
            <Kpi label="Наблюдений за неделю" value={counts.observations} />
            <Kpi label="Источников" value={counts.sources} />
            <Kpi label="Новостей за неделю" value={counts.processedLastWeek} />
            <Kpi label="Новостей за сутки" value={counts.processedLastDay} />
            <Kpi label="Дата актуальности данных" value={counts.lastParsed} />
            <Kpi label="Дата обновления базы" value={counts.lastUpdate} />
          </div>
        </div>
      </section>

      <section className="card pyramid-card">
        <div className="latest-layout">
          {hot5.length ? (
            <div className="latest-row one">
              {hot5.map((item) => <SignalCard key={item.id} item={item} auth={auth} onToggleFavorite={onToggleFavorite} favorite={favorites.some((fav) => fav.id === item.id)} variant="large" />)}
            </div>
          ) : null}

          {hot4.length ? (
            <div className="latest-row two">
              {hot4.map((item) => <SignalCard key={item.id} item={item} auth={auth} onToggleFavorite={onToggleFavorite} favorite={favorites.some((fav) => fav.id === item.id)} variant="medium" />)}
            </div>
          ) : null}

          {hot3.length ? (
            <div className="latest-row three">
              {hot3.map((item) => <SignalCard key={item.id} item={item} auth={auth} onToggleFavorite={onToggleFavorite} favorite={favorites.some((fav) => fav.id === item.id)} variant="small" />)}
            </div>
          ) : null}
        </div>
        <div className="pyramid-footer">
          <Link to="/cards" className="button ghost">Больше</Link>
        </div>
      </section>
    </div>
  )
}

function AboutPage() {
  return (
    <div className="stack">
      <section className="card page-head placeholder-page">
        <h1>Данная страница еще в разработке</h1>
        <p>Скоро здесь появится описание проекта, команды и материалов.</p>
        <img className="placeholder-cat" src="/working-cat.svg" alt="Страница в разработке" />
      </section>
    </div>
  )
}

function DigestsPage() {
  return (
    <div className="stack">
      <section className="card page-head placeholder-page">
        <h1>Данная страница еще в разработке</h1>
        <p>В будущем здесь будет располагаться краткая еженедельная сводка.</p>
        <img className="placeholder-cat" src="/working-cat.svg" alt="Дайджесты в разработке" />
      </section>
    </div>
  )
}

function CardsPage({ signals, overview = {}, favorites = [], auth, onToggleFavorite }) {
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState('hotness')
  const [category, setCategory] = useState([])
  const [source, setSource] = useState([])
  const [hotness, setHotness] = useState([])
  const [timeRange, setTimeRange] = useState('week')
  const [pageSignals, setPageSignals] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [cardsLoading, setCardsLoading] = useState(false)
  const [cardsError, setCardsError] = useState('')

  const buildCardsPath = (offset) => {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
      sort: sortBy,
    })
    if (category.length) params.set('category', category.join(','))
    if (source.length) params.set('source', source.join(','))
    params.set('hotness', hotness.length ? hotness.join(',') : '2,3,4,5')
    if (timeRange !== 'all') params.set('time_range', timeRange)
    if (query.trim()) params.set('q', query.trim())
    return `/api/signals?${params.toString()}`
  }

  const loadCards = async (reset = false) => {
    const offset = reset ? 0 : pageSignals.length
    setCardsLoading(true)
    setCardsError('')
    if (reset) {
      setPageSignals([])
      setHasMore(false)
    }
    try {
      const data = await apiFetch(buildCardsPath(offset))
      const items = data.items || []
      setPageSignals((prev) => reset ? items : [...prev, ...items])
      setHasMore(Boolean(data.has_more))
    } catch (error) {
      setCardsError(error.message)
    } finally {
      setCardsLoading(false)
    }
  }

  useEffect(() => {
    let alive = true
    setCardsLoading(true)
    setCardsError('')
    setPageSignals([])
    setHasMore(false)
    ;(async () => {
      try {
        const data = await apiFetch(buildCardsPath(0))
        if (!alive) return
        setPageSignals(data.items || [])
        setHasMore(Boolean(data.has_more))
      } catch (error) {
        if (alive) setCardsError(error.message)
      } finally {
        if (alive) setCardsLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [sortBy, category, source, hotness, timeRange, query])

  const submitSearch = (event) => {
    event.preventDefault()
    setQuery(searchInput.trim())
  }

  const topics = useMemo(() => {
    const values = overview.category_options || signals.filter((item) => Number(item.hotness) !== 1).map((item) => item.category).filter(Boolean)
    return [...new Set(values)].map((value) => ({ value, label: value }))
  }, [signals, overview.category_options])

  const sources = useMemo(() => {
    const values = overview.source_options || signals.filter((item) => Number(item.hotness) !== 1).map((item) => item.source_name).filter(Boolean)
    return [...new Set(values)].map((value) => ({ value, label: value }))
  }, [signals, overview.source_options])

  return (
    <div className="stack">
      {/* 1. Заголовок страницы */}
      <section className="card page-head">
        <h1>FinTech News</h1>
        <p>Используйте фильтры ниже для сортировки и поиска по категориям.</p>
        <form className="search-form" onSubmit={submitSearch}>
          <input
            className="search-input"
            placeholder="Поиск по всей базе. Нажмите Enter для запуска."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <button className="button ghost" type="submit" disabled={cardsLoading}>
            Найти
          </button>
        </form>

        {/* 2. Твой новый красивый тулбар */}
        <div className="cards-toolbar">
          <CustomSelect
            value={sortBy}
            onChange={setSortBy}
            options={[
              { value: 'time_desc', label: 'Сначала новые' },
              { value: 'time_asc', label: 'Сначала старые' },
              { value: 'hotness', label: 'По hotness' }
            ]}
          />

          <MultiSelect
            value={category}
            values={category}
            onChange={setCategory}
            options={topics}
            placeholder="Все темы"
          />

          <MultiSelect
            value={source}
            values={source}
            onChange={setSource}
            options={sources}
            placeholder="Все источники"
          />

          <MultiSelect
            value={hotness}
            values={hotness}
            onChange={setHotness}
            options={[
              { value: '5', label: 'Hotness: 5' },
              { value: '4', label: 'Hotness: 4' },
              { value: '3', label: 'Hotness: 3' },
              { value: '2', label: 'Hotness: 2' }
            ]}
            placeholder="Любой hotness"
          />

          <CustomSelect
            value={timeRange}
            onChange={setTimeRange}
            options={[
              { value: 'all', label: 'Любое время' },
              { value: 'day', label: 'За сутки' },
              { value: 'week', label: 'За неделю' },
              { value: 'month', label: 'За месяц' }
            ]}
          />

          <div className="mini-stat">Избранных: {favorites.length}</div>
        </div>
      </section>

      {/* 3. САМОЕ ГЛАВНОЕ: Сетка с карточками, которую мы потеряли */}
      <section className="cards-grid">
        {cardsError ? (
          <div className="card center-card" style={{ gridColumn: '1 / -1' }}>
            <p className="muted">{cardsError}</p>
          </div>
        ) : pageSignals.length > 0 ? (
          pageSignals.map((item) => (
            <SignalCard
              key={item.id}
              item={item}
              auth={auth}
              onToggleFavorite={onToggleFavorite}
              favorite={favorites.some((fav) => fav.id === item.id)}
            />
          ))
        ) : (
          <div className="card center-card" style={{ gridColumn: '1 / -1' }}>
            <p className="muted">{cardsLoading ? 'Пожалуйста подождите, данные загружаются.' : 'По выбранным фильтрам ничего не найдено.'}</p>
          </div>
        )}
      </section>

      {hasMore ? (
        <div className="load-more-row">
          <button className="button ghost" onClick={() => loadCards(false)} disabled={cardsLoading}>
            {cardsLoading ? 'Загрузка...' : `Загрузить ещё ${PAGE_SIZE}`}
          </button>
        </div>
      ) : null}
    </div>
  )
}

function SignalDetailPage({ signals, favorites, auth, onToggleFavorite }) {
  const { id } = useParams();
  const cachedItem = signals.find((s) => String(s.id) === String(id));
  const [remoteItem, setRemoteItem] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true

    if (cachedItem) {
      setRemoteItem(null)
      setError('')
      return () => {
        alive = false
      }
    }

    setLoading(true)
    setError('')
    setRemoteItem(null)

    apiFetch(`/api/signals/${id}`)
      .then((data) => {
        if (alive) setRemoteItem(data.item || null)
      })
      .catch((err) => {
        if (alive) setError(err.message)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })

    return () => {
      alive = false
    }
  }, [id, cachedItem])

  const item = cachedItem || remoteItem;

  if (loading) return <div className="card center-card"><p className="muted">Пожалуйста подождите, данные загружаются.</p></div>;
  if (!item) return <div className="card">{error || 'Карточка не найдена'}</div>;

  const sourceUrls = Array.isArray(item.source_urls) && item.source_urls.length
    ? item.source_urls.filter(Boolean)
    : [item.url].filter(Boolean);
  const favorite = favorites.some((fav) => fav.id === item.id)

  return (
    <section className="card detail-card">
      <div className="detail-head">
        <div>
          <div className="detail-tags">
            <span className={`pill ${categoryClass(item.category)}`}>{item.category}</span>
            <span className={`hot-badge ${hotnessClass(item.hotness)}`}>Hotness {item.hotness}</span>
          </div>
          <h1>{item.headline}</h1>
        </div>
        <div className="detail-buttons">
          <button className="button icon-button ghost" title="Скопировать ссылку" onClick={() => copySignalLink(item.id)}>
            ⧉
          </button>
          <button className="button icon-button primary favorite-button" onClick={() => onToggleFavorite(item.id)}>
            {favorite ? '★' : '☆'}
          </button>
        </div>
      </div>

      <div className="detail-grid">
        <InfoCard title="Кратко" text={item.summary} />
        <InfoCard title="Актуальность" text={item.why_now} />

        <div className="info-card sources-card">
          <h3>Источники</h3>
          <p className="muted source-hint">{formatDate(item.published_at || item.created_at)}</p>
          <SourceLinks item={{ ...item, source_urls: sourceUrls }} />
        </div>
      </div>
    </section>
  )
}

function SignalCard({ item, auth, onToggleFavorite, favorite = false, variant = 'default' }) {
  const published = item.published_at || item.created_at
  const navigate = useNavigate()

  const openCard = () => {
    navigate(`/signals/${item.id}`)
  }

  const openFromKeyboard = (event) => {
    if (event.target?.closest?.('button, a')) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openCard()
    }
  }

  return (
    <article
      className={`signal-card variant-${variant}`}
      onClick={openCard}
      onKeyDown={openFromKeyboard}
      role="button"
      tabIndex={0}
    >
      <div className="signal-top">
        <div className="signal-headline">
          <span className={`pill ${categoryClass(item.category)}`}>{item.category}</span>
          <h3>{item.headline}</h3>
        </div>
        <span className={`hot-badge ${hotnessClass(item.hotness)}`}>Hotness {item.hotness}</span>
      </div>

      <div className="signal-meta">
        <span>{formatDate(published)}</span>
      </div>

      {item.summary ? <p>{item.summary}</p> : null}
      {variant !== 'small' && item.why_now ? <p><b>Актуальность:</b> {item.why_now}</p> : null}

      <SourceLinks item={item} compact />

      <div className="signal-actions">
        <button className="button icon-button ghost" title="Скопировать ссылку" onClick={(event) => { event.stopPropagation(); copySignalLink(item.id) }}>
          ⧉
        </button>
        <button className="button icon-button primary favorite-button" title={favorite ? 'Убрать из избранного' : 'В избранное'} onClick={(event) => { event.stopPropagation(); onToggleFavorite?.(item.id) }}>
          {favorite ? '★' : '☆'}
        </button>
      </div>
    </article>
  )
}

function SavedPage({ auth, favorites, onToggleFavorite }) {
  const savedSignals = useMemo(() => {
    return favorites || []
  }, [favorites])

  if (!auth) {
    return (
      <div className="card center-card">
        <h1>Сначала войди в аккаунт</h1>
        <p>Избранное доступно после входа.</p>
      </div>
    )
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Избранные новости</h1>
      </section>

      <section className="cards-grid">
        {savedSignals.map((item) => (
          <SignalCard
            key={item.id}
            item={item}
            onToggleFavorite={onToggleFavorite}
            favorite
          />
        ))}
      </section>
    </div>
  )
}

function NotificationsPage({ auth, overview = {}, notifications, settings, onSaveSettings, onClear, onRead }) {
  const [rules, setRules] = useState(settings.length ? settings : [{ theme: '', source_name: '', hotness_min: '' }])
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [clearing, setClearing] = useState(false)
  const unreadTotal = notifications.filter((item) => !item.read).length

  useEffect(() => {
    setRules(settings.length ? settings : [{ theme: '', source_name: '', hotness_min: '' }])
  }, [settings])

  const topicOptions = useMemo(() => {
    const values = new Set(overview.category_options || [])
    ;(rules || []).forEach((rule) => {
      if (rule.theme) values.add(rule.theme)
    })
    return [{ value: '', label: 'Любая категория' }, ...[...values].map((value) => ({ value, label: value }))]
  }, [rules, overview.category_options])

  const sourceOptions = useMemo(() => {
    const values = new Set(overview.source_options || [])
    ;(rules || []).forEach((rule) => {
      if (rule.source_name) values.add(rule.source_name)
    })
    return [{ value: '', label: 'Любой источник' }, ...[...values].sort().map((value) => ({ value, label: value }))]
  }, [rules, overview.source_options])

  const hotnessOptions = [
    { value: '', label: 'Любая важность' },
    { value: '5', label: 'Только hotness 5' },
    { value: '4', label: 'Hotness 4 и выше' },
    { value: '3', label: 'Hotness 3 и выше' },
    { value: '2', label: 'Hotness 2 и выше' }
  ];

  const addRule = () => {
    setRules((prev) => [...prev, { theme: '', source_name: '', hotness_min: '' }])
  }

  const updateRule = (index, patch) => {
    setRules((prev) => prev.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)))
  }

  const removeRule = (index) => {
    setRules((prev) => {
      const next = prev.filter((_, i) => i !== index)
      return next.length ? next : [{ theme: '', source_name: '', hotness_min: '' }]
    })
  }

  const saveRules = async () => {
    const clean = rules
      .map((rule) => ({
        theme: rule.theme || '',
        source_name: rule.source_name || '',
        hotness_min: rule.hotness_min === '' ? '' : Number(rule.hotness_min),
      }))
      .filter((rule) => rule.theme || rule.source_name || rule.hotness_min !== '')

    setSaving(true)
    setNotice('')
    try {
      await onSaveSettings(clean)
      setNotice(clean.length ? 'Правила сохранены. Новые уведомления будут приходить по ним.' : 'Правила очищены. Новые сигналы будут приходить без фильтров.')
    } catch (error) {
      setNotice(error.message)
    } finally {
      setSaving(false)
    }
  }

  const clearAllNotifications = async () => {
    setClearing(true)
    setNotice('')
    try {
      await onClear()
      setNotice('Лента уведомлений очищена.')
    } catch (error) {
      setNotice(error.message)
    } finally {
      setClearing(false)
    }
  }

  const openNotification = (item) => {
    if (item.signal_id) {
      openExternalTab(routeUrl(`/signals/${item.signal_id}`))
    }
    if (!item.read) {
      onRead?.(item.id).catch(() => {})
    }
  }

  if (!auth) {
    return (
      <div className="card center-card">
        <h1>Войди в аккаунт</h1>
        <p>Настройки уведомлений доступны после входа.</p>
      </div>
    )
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Уведомления</h1>
        <p>Настройте правила для новых сигналов. Каждое правило работает отдельно: если новость подходит хотя бы под одно, она попадёт в ленту.</p>
        <div className="notification-stats">
          <div className="mini-stat">Правил: {settings.length}</div>
          <div className="mini-stat">Новых: {unreadTotal}</div>
          <div className="mini-stat">Всего: {notifications.length}</div>
        </div>
      </section>

      <section className="card notification-settings-card">
        <div className="section-head">
          <div>
            <h2>Правила уведомлений</h2>
            <p className="muted">Категории и источники подтягиваются из текущей базы. Пустое поле означает, что ограничение не применяется.</p>
          </div>
          <button className="button ghost" onClick={addRule}>Добавить правило</button>
        </div>

        <div className="rules-list">
          {rules.map((rule, index) => (
            <div className="notification-rule-card" key={index}>
              <div className="rule-card-head">
                <span>Правило {index + 1}</span>
                <button className="button ghost" onClick={() => removeRule(index)}>Удалить</button>
              </div>

              <label className="field">
                <span>Категория</span>
                <CustomSelect
                  value={rule.theme}
                  options={topicOptions}
                  onChange={(val) => updateRule(index, { theme: val })}
                />
              </label>

              <label className="field">
                <span>Источник</span>
                <CustomSelect
                  value={rule.source_name}
                  options={sourceOptions}
                  onChange={(val) => updateRule(index, { source_name: val })}
                />
              </label>

              <label className="field">
                <span>Важность</span>
                <CustomSelect
                  value={rule.hotness_min}
                  options={hotnessOptions}
                  onChange={(val) => updateRule(index, { hotness_min: val })}
                />
              </label>
            </div>
          ))}
        </div>

        <div className="notification-actions">
          <button className="button primary" onClick={saveRules} disabled={saving}>
            {saving ? 'Сохраняю...' : 'Сохранить правила'}
          </button>
          {notice ? <div className="flash">{notice}</div> : null}
        </div>
      </section>

      <section className="card notification-feed-card">
        <div className="section-head">
          <div>
            <h2>Лента</h2>
            <p className="muted">Здесь появляются только новые карточки после обновления базы.</p>
          </div>
          <button className="button ghost" onClick={clearAllNotifications} disabled={clearing || !notifications.length}>
            {clearing ? 'Очищаю...' : 'Очистить'}
          </button>
        </div>

        {notifications.length ? (
          <div className="notification-list">
            {notifications.map((item) => (
              <button key={item.id} className={`notification-card ${item.read ? '' : 'unread'}`} onClick={() => openNotification(item)}>
                <div className="notification-title-row">
                  <span className="notification-title">{item.title}</span>
                  {!item.read ? <span className="mini-pill notification-new">Новое</span> : null}
                </div>
                {item.message ? <div className="notification-message">{item.message}</div> : null}
                <div className="notification-subtitle">{formatDate(item.created_at)}</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <p className="muted">Пока нет новых уведомлений.</p>
          </div>
        )}
      </section>
    </div>
  )
}

function AccountPage({ auth, onSaveProfile }) {
  const [fullName, setFullName] = useState(auth?.user?.full_name || '')
  const [email, setEmail] = useState(auth?.user?.email || '')
  const [bio, setBio] = useState(auth?.user?.bio || '')
  const [avatarUrl, setAvatarUrl] = useState(auth?.user?.avatar_url || '')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [showRenewPlans, setShowRenewPlans] = useState(false)
  const [renewPlan, setRenewPlan] = useState('basic')

  useEffect(() => {
    setFullName(auth?.user?.full_name || '')
    setEmail(auth?.user?.email || '')
    setBio(auth?.user?.bio || '')
    setAvatarUrl(auth?.user?.avatar_url || '')
  }, [auth])

  const handleAvatar = (file) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setAvatarUrl(String(reader.result || ''))
    reader.readAsDataURL(file)
  }

  const submitRenewal = (event) => {
    event.preventDefault()
    setNotice('На данный момент не доступна')
  }

  const save = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      await onSaveProfile({
        full_name: fullName,
        email,
        bio,
        avatar_url: avatarUrl,
      })
      setNotice('Профиль обновлён')
    } catch (error) {
      setNotice(error.message)
    } finally {
      setSaving(false)
    }
  }

  if (!auth) {
    return (
      <div className="card center-card">
        <h1>Сначала войди в аккаунт</h1>
        <p>После входа здесь можно менять данные профиля и аватарку.</p>
        <div className="hero-actions" style={{ justifyContent: 'center' }}>
          <Link to="/login" className="button primary">Войти</Link>
          <Link to="/register" className="button ghost">Регистрация</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="stack">
      <section className="card profile-card">
        <div className="avatar-preview">
          {avatarUrl ? <img src={avatarUrl} alt="avatar" /> : <span>{String(auth.user?.full_name || '?').slice(0, 1).toUpperCase()}</span>}
        </div>
        <div>
          {auth.user.role === 'admin' ? <span className="eyebrow">{auth.user.role}</span> : null}
          <h1>{auth.user.full_name}</h1>
          <p>{auth.user.email}</p>
          <p>{auth.user.activated ? 'Аккаунт активирован' : 'Аккаунт не активирован'}</p>
        </div>
      </section>

      <section className="card subscription-card">
        <div>
          <span className="eyebrow">Подписка</span>
          <h2>{planLabel(auth.user.subscription_plan)}</h2>
          <p>{subscriptionStatusLabel(auth.user.subscription_status)}</p>
          <p className="muted">
            {auth.user.subscription_expires_at ? `Действует до ${compactDate(auth.user.subscription_expires_at)}` : 'Без ограничения срока'}
          </p>
        </div>
        {auth.user.role !== 'admin' ? (
          <button
            className="button ghost"
            onClick={() => {
              setShowRenewPlans((value) => !value)
              setNotice('')
            }}
          >
            Продлить
          </button>
        ) : null}
      </section>

      {showRenewPlans ? (
        <section className="card form-card">
          <h2>Продление подписки</h2>
          <form className="form-grid" onSubmit={submitRenewal}>
            <PlanSelector selectedPlan={renewPlan} onSelect={setRenewPlan} includeDemo={false} />
            <button className="button primary full" type="submit">
              Подключить тариф
            </button>
          </form>
        </section>
      ) : null}

      <section className="card form-card">
        <h2>Редактирование профиля</h2>
        <form className="form-grid" onSubmit={save}>
          <label className="field">
            <span>Логин</span>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </label>
          <label className="field">
            <span>Почта</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span>Короткое описание</span>
            <textarea value={bio} onChange={(e) => setBio(e.target.value)} rows={4} />
          </label>
          <label className="field">
            <span>Аватарка</span>
            <input type="file" accept="image/*" onChange={(e) => handleAvatar(e.target.files?.[0])} />
          </label>
          <button className="button primary full" type="submit" disabled={saving}>
            {saving ? 'Сохраняю...' : 'Сохранить профиль'}
          </button>
        </form>
        {notice ? <div className="flash">{notice}</div> : null}
      </section>
    </div>
  )
}

function PlanSelector({ selectedPlan, onSelect, includeDemo = true }) {
  const plans = [
    {
      id: 'demo',
      title: 'Демо-доступ',
      price: '0 ₽',
      term: '7 дней',
      description: 'Демо-доступ ко всем возможностям Red Cat TrendWatcher',
    },
    {
      id: 'basic',
      title: 'Basic',
      price: 'Скоро',
      term: '31 день',
      description: 'Базовый мониторинг трендов, избранное и уведомления.',
      unavailable: true,
    },
    {
      id: 'plus',
      title: 'Plus',
      price: 'Скоро',
      term: '31 день',
      description: 'Расширенная витрина, персональные правила и приоритетные сценарии.',
      unavailable: true,
    },
  ].filter((plan) => includeDemo || plan.id !== 'demo')

  return (
    <div className="plan-options" role="radiogroup" aria-label="Тарифный план">
      {plans.map((plan) => (
        <button
          key={plan.id}
          type="button"
          className={`plan-card plan-card-button ${selectedPlan === plan.id ? 'selected' : ''}`}
          onClick={() => onSelect(plan.id)}
          role="radio"
          aria-checked={selectedPlan === plan.id}
        >
          <div>
            <h3>{plan.title}</h3>
            <p>{plan.description}</p>
            <span className="plan-term">{plan.term}</span>
          </div>
          <strong className={plan.unavailable ? 'muted-price' : ''}>{plan.price}</strong>
        </button>
      ))}
    </div>
  )
}

function RegisterPage({ onAuth }) {
  const [step, setStep] = useState(1)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [selectedPlan, setSelectedPlan] = useState('demo')
  const [notice, setNotice] = useState('')
  const navigate = useNavigate()

  const register = async (e) => {
    e.preventDefault()
    try {
      const data = await apiFetch('/api/register', {
        method: 'POST',
        body: JSON.stringify({
          full_name: fullName,
          email,
          password,
        }),
      })
      setEmail(data.user.email)
      setStep(2)
      setNotice('')
    } catch (error) {
      if (error.data?.requires_activation) {
        const activationEmail = encodeURIComponent(error.data.email || email)
        navigate(`/activate?email=${activationEmail}`)
        return
      }
      setNotice(error.message)
    }
  }

  const activate = async (e) => {
    e.preventDefault()
    if (selectedPlan !== 'demo') {
      setNotice('На данный момент не доступна')
      return
    }
    try {
      const data = await apiFetch('/api/activate', {
        method: 'POST',
        body: JSON.stringify({
          email,
          plan: selectedPlan,
        }),
      })
      onAuth(data)
      navigate('/account')
    } catch (error) {
      setNotice(error.data?.requires_activation ? 'Аккаунт нужно активировать. Выберите тарифный план.' : error.message)
    }
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Регистрация аккаунта</h1>
        <p>После регистрации выберите тарифный план для доступа к сервису.</p>
      </section>

      <section className="card form-card">
        {step === 1 ? (
          <form className="form-grid" onSubmit={register}>
            <label className="field">
              <span>Логин</span>
              <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </label>
            <label className="field">
              <span>Почта</span>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="field">
              <span>Пароль</span>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <button className="button primary full" type="submit">Продолжить</button>
          </form>
        ) : (
          <form className="form-grid" onSubmit={activate}>
            <PlanSelector selectedPlan={selectedPlan} onSelect={setSelectedPlan} />
            <button className="button primary full" type="submit">
              Подключить тариф
            </button>
          </form>
        )}

        {notice ? <div className="flash">{notice}</div> : null}
      </section>
    </div>
  )
}

function ActivationPage({ onAuth }) {
  const location = useLocation()
  const navigate = useNavigate()
  const params = new URLSearchParams(location.search)
  const [email, setEmail] = useState(params.get('email') || '')
  const [selectedPlan, setSelectedPlan] = useState('demo')
  const [notice, setNotice] = useState('Аккаунт нужно активировать.')

  const activate = async (event) => {
    event.preventDefault()
    if (selectedPlan !== 'demo') {
      setNotice('На данный момент не доступна')
      return
    }
    try {
      const data = await apiFetch('/api/activate', {
        method: 'POST',
        body: JSON.stringify({
          email,
          plan: selectedPlan,
        }),
      })
      onAuth(data)
      navigate('/account')
    } catch (error) {
      setNotice(error.message)
    }
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Активация аккаунта</h1>
        <p>Выберите тарифный план для доступа к сервису.</p>
      </section>

      <section className="card form-card">
        <form className="form-grid" onSubmit={activate}>
          <label className="field">
            <span>Почта</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <PlanSelector selectedPlan={selectedPlan} onSelect={setSelectedPlan} />
          <button className="button primary full" type="submit">
            Подключить тариф
          </button>
        </form>
        {notice ? <div className="flash">{notice}</div> : null}
      </section>
    </div>
  )
}

function LoginPage({ onAuth }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [notice, setNotice] = useState('')
  const navigate = useNavigate()

  const login = async (e) => {
    e.preventDefault()
    try {
      const data = await apiFetch('/api/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      onAuth(data)
      navigate('/account')
    } catch (error) {
      if (error.data?.requires_activation) {
        const activationEmail = encodeURIComponent(error.data.email || email)
        navigate(`/activate?email=${activationEmail}`)
        return
      }
      setNotice(error.message)
    }
  }

  return (
    <div className="stack">
      <section className="card form-card">
        <div>
          <h1>Войти в аккаунт</h1>
        </div>
        <form className="form-grid" onSubmit={login}>
          <label className="field">
            <span>Почта</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span>Пароль</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <button className="button primary full" type="submit">Войти</button>
        </form>
        {notice ? <div className="flash">{notice}</div> : null}
      </section>
    </div>
  )
}

function AdminUsersPage({ auth, users, refreshAdmin }) {
  const [current, setCurrent] = useState(null)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [activated, setActivated] = useState(false)
  const [notice, setNotice] = useState('')

  const updateSubscription = async (user, patch) => {
    try {
      await apiFetch(`/api/admin/subscriptions/${user.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          subscription_plan: user.subscription_plan || '',
          subscription_status: user.subscription_status || 'inactive',
          ...patch,
        }),
      }, auth.token)
      await refreshAdmin(auth.token)
      setNotice('Подписка обновлена')
    } catch (error) {
      setNotice(error.message)
    }
  }

  const submitRenewal = (event) => {
    event.preventDefault()
    setNotice('На данный момент не доступна')
  }

  const openEdit = (user) => {
    setCurrent(user)
    setFullName(user.full_name)
    setEmail(user.email)
    setActivated(user.activated)
  }

  const save = async (e) => {
    e.preventDefault()
    if (!current) return
    try {
      await apiFetch(`/api/admin/users/${current.id}`, {
        method: 'PUT',
        body: JSON.stringify({ full_name: fullName, email, activated }),
      }, auth.token)

      await refreshAdmin(auth.token)
      setNotice('Пользователь обновлён')
    } catch (error) {
      setNotice(error.message)
    }
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Пользователи</h1>
        <p>Таблица аккаунтов, подписок и срока доступа.</p>
      </section>

      <section className="grid-2">
        <div className="card table-wrap">
          <table className="market-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Логин</th>
                <th>Почта</th>
                <th>Роль</th>
                <th>Подписка</th>
                <th>Статус</th>
                <th>До</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.id}</td>
                  <td>{user.full_name}</td>
                  <td>{user.email}</td>
                  <td>{user.role}</td>
                  <td>
                    {user.email === 'manager@redcat.tu' ? planLabel(user.subscription_plan) : (
                      <CustomSelect
                        value={user.subscription_plan || ''}
                        options={[
                          { value: '', label: 'Без подписки' },
                          { value: 'demo', label: 'Демо · 7 дней' },
                          { value: 'basic', label: 'Basic · 31 день' },
                          { value: 'plus', label: 'Plus · 31 день' },
                        ]}
                        onChange={(value) => updateSubscription(user, { subscription_plan: value })}
                      />
                    )}
                  </td>
                  <td>
                    {user.email === 'manager@redcat.tu' ? subscriptionStatusLabel(user.subscription_status) : (
                      <CustomSelect
                        value={user.subscription_status || 'inactive'}
                        options={[
                          { value: 'active', label: 'Активна' },
                          { value: 'inactive', label: 'Отключена' },
                          { value: 'expired', label: 'Истекла' },
                        ]}
                        onChange={(value) => updateSubscription(user, { subscription_status: value })}
                      />
                    )}
                  </td>
                  <td>{user.subscription_expires_at ? compactDate(user.subscription_expires_at) : '—'}</td>
                  <td>
                    <button className="button ghost" onClick={() => openEdit(user)}>Редактировать</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card form-card">
          <h3>Редактирование</h3>
          {current ? (
            <form className="form-grid" onSubmit={save}>
              <label className="field">
                <span>Логин</span>
                <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
              </label>
              <label className="field">
                <span>Почта</span>
                <input value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label className="promo-switch">
                <input type="checkbox" checked={activated} onChange={(e) => setActivated(e.target.checked)} />
                Активирован
              </label>
              <button className="button primary full" type="submit">Сохранить</button>
            </form>
          ) : (
            <p className="muted">Выбери пользователя слева.</p>
          )}
          {notice ? <div className="flash">{notice}</div> : null}
        </div>
      </section>
    </div>
  )
}

function AdminSubscriptionsPage({ auth, users, refreshAdmin }) {
  const [notice, setNotice] = useState('')

  const updateSubscription = async (user, patch) => {
    try {
      await apiFetch(`/api/admin/subscriptions/${user.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          subscription_plan: user.subscription_plan || '',
          subscription_status: user.subscription_status || 'inactive',
          ...patch,
        }),
      }, auth.token)
      await refreshAdmin(auth.token)
      setNotice('Подписка обновлена')
    } catch (error) {
      setNotice(error.message)
    }
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Подписки</h1>
        <p>Управление демо-доступом пользователей.</p>
      </section>

      <section className="card table-wrap">
        <table className="market-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Логин</th>
              <th>Почта</th>
              <th>Тариф</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td>{user.id}</td>
                <td>{user.full_name}</td>
                <td>{user.email}</td>
                <td>
                  <CustomSelect
                    value={user.subscription_plan || ''}
                    options={[
                      { value: '', label: 'Без тарифа' },
                      { value: 'demo', label: 'Демо-доступ · 0 ₽' },
                    ]}
                    onChange={(value) => updateSubscription(user, { subscription_plan: value })}
                  />
                </td>
                <td>
                  <CustomSelect
                    value={user.subscription_status || 'inactive'}
                    options={[
                      { value: 'active', label: 'Активна' },
                      { value: 'inactive', label: 'Отключена' },
                    ]}
                    onChange={(value) => updateSubscription(user, { subscription_status: value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {notice ? <div className="flash">{notice}</div> : null}
      </section>
    </div>
  )
}

function RequireAdmin({ auth, children }) {
  if (!auth) return <Navigate to="/login" replace />
  if (auth.user?.role !== 'admin') return <Navigate to="/" replace />
  return children
}

function Kpi({ label, value }) {
  const isText = Number.isNaN(Number(value))
  return (
    <div className="kpi">
      <div className={`kpi-value ${isText ? 'text-value' : ''}`}>{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  )
}

function InfoCard({ title, text }) {
  return (
    <article className="info-card">
      <h3>{title}</h3>
      <p>{text}</p>
    </article>
  )
}
