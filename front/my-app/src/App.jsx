import React, { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'

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
  const selectedLabel = options.find(o => String(o.value) === String(value))?.label || value;

  return (
    <div className="custom-select">
      <div className="select-trigger" onClick={() => setIsOpen(!isOpen)}>
        {selectedLabel}
      </div>

      {isOpen && (
        <>
          {/* Прозрачная подложка, чтобы закрыть список при клике в любое место */}
<div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={() => setIsOpen(false)} />
          <div className="select-options">
            {options.map((opt) => (
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
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function MultiSelect({ values, onChange, options, placeholder }) {
  const [isOpen, setIsOpen] = React.useState(false)
  const selected = Array.isArray(values) ? values : []
  const selectedLabels = options
    .filter((option) => selected.includes(String(option.value)))
    .map((option) => option.label)
  const label = selectedLabels.length ? selectedLabels.join(', ') : placeholder

  const toggleValue = (value) => {
    const text = String(value)
    onChange(selected.includes(text)
      ? selected.filter((item) => item !== text)
      : [...selected, text])
  }

  return (
    <div className="custom-select multi-select">
      <div className="select-trigger" onClick={() => setIsOpen(!isOpen)}>
        {label}
      </div>

      {isOpen && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={() => setIsOpen(false)} />
          <div className="select-options">
            <div
              className={`select-option ${selected.length === 0 ? 'active' : ''}`}
              onClick={() => onChange([])}
            >
              {placeholder}
            </div>
            {options.map((opt) => (
              <div
                key={opt.value}
                className={`select-option ${selected.includes(String(opt.value)) ? 'active' : ''}`}
                onClick={() => toggleValue(opt.value)}
              >
                {opt.label}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function routeUrl(path) {
  return `${window.location.origin}${window.location.pathname}#${path}`
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
    throw new Error(data.error || data.message || data.update?.message || 'Что-то пошло не так')
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

  useEffect(() => {
    setItems(Array.isArray(market) ? market : (market?.items || []))
    setHasMore(Boolean(market?.has_more))
  }, [market])

  const loadMore = async () => {
    setLoading(true)
    try {
      const data = await apiFetch(`/api/market?limit=${PAGE_SIZE}&offset=${items.length}`)
      setItems((prev) => [...prev, ...(data.items || [])])
      setHasMore(Boolean(data.has_more))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <section className="card page-head">
        <h1>Статистика MOEX</h1>
      </section>

      <div className="card" style={{ marginTop: '20px', overflowX: 'auto', padding: '0' }}>
        {items.length ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px' }}>
            <thead>
              <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
                <th style={thStyle}>Дата</th>
                <th style={thStyle}>ЦБ в листинге</th>
                <th style={thStyle}>Общий объем, тыс. ₽</th>
                <th style={thStyle}>Сделок</th>
                <th style={thStyle}>Лидер торгов</th>
                <th style={thStyle}>Объем лидера, тыс. ₽</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={index} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={tdStyle}>{item.date}</td>
                  <td style={tdStyle}>{item.sec_count}</td>
                  <td style={tdStyle}>{item.total_value}</td>
                  <td style={tdStyle}>{item.trades}</td>
                  <td style={tdStyle}><strong>{item.top_ticker}</strong></td>
                  <td style={tdStyle}>{item.top_value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ padding: '20px' }}>Данные не найдены в базе.</div>
        )}
      </div>
      {hasMore ? (
        <div className="load-more-row">
          <button className="button ghost" onClick={loadMore} disabled={loading}>
            {loading ? 'Загружаю...' : `Загрузить ещё ${PAGE_SIZE}`}
          </button>
        </div>
      ) : null}
    </div>
  );
}

// Стили для ячеек
const thStyle = { padding: '15px', textAlign: 'left', color: '#666', fontSize: '0.9rem' };
const tdStyle = { padding: '15px', fontSize: '0.95rem' };
// Компонент для защиты путей
function ProtectedRoute({ auth, children }) {
  if (!auth) {
    // Если не авторизован — редирект на логин (или на главную с алертом)
    return <Navigate to="/login" replace />;
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
  const [settings, setSettings] = useState([])
  const [users, setUsers] = useState([])
  const [promos, setPromos] = useState([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [toast, setToast] = useState(null)
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
    setSettings([])
    setUsers([])
    setPromos([])
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
    setSettings(prefs.items || [])
    setToast((notif.items || [])[0] || null)
  }

  const refreshAdmin = async (token = auth?.token) => {
    if (!token) return
    const [usersData, promosData] = await Promise.all([
      apiFetch('/api/admin/users', {}, token),
      apiFetch('/api/admin/promo-codes', {}, token),
    ])
    setUsers(usersData.items || [])
    setPromos(promosData.items || [])
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

  useEffect(() => {
    if (!toast && notifications.length) {
      setToast(notifications[0])
    }
  }, [notifications, toast])

  const flash = (text) => {
    setMessage(text)
    window.clearTimeout(window.__redcatFlashTimer)
    window.__redcatFlashTimer = window.setTimeout(() => setMessage(''), 2500)
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
            <h2>Загружаю проект</h2>
            <p>Подтягиваю сигналы, MOEX и настройки из базы.</p>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="app-shell">
      {toast ? <ToastBar item={toast} onClose={() => setToast(null)} /> : null}

      <TopBar auth={auth} onLogout={logout} />

      {message ? <div className="top-message">{message}</div> : null}

     <main className="page-wrap">
  <Routes>
    {/* Открытые страницы */}
    <Route path="/" element={<HomePage signals={signalCardList} overview={overview} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} onRunUpdate={runUpdate} updating={updating} />} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="/register" element={auth ? <Navigate to="/account" replace /> : <RegisterPage onAuth={persistAuth} />} />
    <Route path="/login" element={auth ? <Navigate to="/account" replace /> : <LoginPage onAuth={persistAuth} />} />

    {/* Защищенные страницы (только для авторизованных) */}
    <Route path="/cards" element={
      <ProtectedRoute auth={auth}>
        <CardsPage signals={signalCardList} overview={overview} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} />
      </ProtectedRoute>
    } />
    <Route path="/offtop-news" element={
      <ProtectedRoute auth={auth}>
        <OfftopNewsPage signals={signalCardList} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} />
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
        <NotificationsPage auth={auth} signals={signalCardList} notifications={notifications} settings={settings} onSaveSettings={saveNotificationSettings} onClear={clearNotifications} />
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

    {/* Админка (уже защищена RequireAdmin, который работает по тому же принципу) */}
    <Route path="/admin/users" element={
      <RequireAdmin auth={auth}><AdminUsersPage auth={auth} users={users} refreshAdmin={refreshAdmin} /></RequireAdmin>
    } />
    <Route path="/admin/promos" element={
      <RequireAdmin auth={auth}><AdminPromosPage auth={auth} promos={promos} refreshAdmin={refreshAdmin} /></RequireAdmin>
    } />

    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
      </main>

      <Footer />
    </div>
  )
}

function TopBar({ auth, onLogout }) {
  const [open, setOpen] = useState(false)

  const links = [
    ['/', 'Главная'],
    ['/about', 'О проекте'],
    ['/cards', 'FinTech News'],
    ['/offtop-news', 'Offtop News'],
    ['/moex', 'MOEX'],
    ['/notifications', 'Уведомления'],
  ]

  const isAdmin = auth?.user?.role === 'admin'

  if (isAdmin) {
    links.push(['/admin/users', 'Админ users'], ['/admin/promos', 'Админ promos'])
  }

  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <img src="/logoRedCat.png" alt="Red Cat" />
        <div>
          <div className="brand-title">Red Cat</div>
          <div className="brand-subtitle">Trendwatcher</div>
        </div>
      </Link>

      <nav className="nav">
        {links.map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            {label}
          </NavLink>
        ))}

        {auth ? (
          <div className="account-dropdown" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
            <NavLink to="/account" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              {auth.user?.full_name || 'Профиль'}
            </NavLink>
            {open ? (
              <div className="dropdown-menu">
                <NavLink to="/saved" className="dropdown-item">Сохранённые</NavLink>
                {isAdmin ? (
                  <NavLink to="/admin/users" className="dropdown-item">Админка</NavLink>
                ) : null}
                <button onClick={onLogout}>Выйти</button>
              </div>
            ) : null}
          </div>
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
        <div>
          <h1>Опережай тренды. Управляй будущим.</h1>
          <p>Учебный проект в рамках хакатона АльфаБанка для Лицея НИУ ВШЭ</p>
          <div className="hero-actions">
            <Link to="/cards" className="button primary">Открыть FinTech News</Link>
            <Link to="/offtop-news" className="button ghost">Offtop News</Link>
            <button className="button ghost" onClick={onRunUpdate} disabled={updating}>
              {updating ? 'Запускаю...' : 'Обновить базу'}
            </button>
          </div>
        </div>

        <div className="hero-panel">
          <div className="kpi-grid">
            <Kpi label="Наблюдений" value={counts.observations} />
            <Kpi label="Источников" value={counts.sources} />
            <Kpi label="Новостей за неделю" value={counts.processedLastWeek} />
            <Kpi label="Новостей за сутки" value={counts.processedLastDay} />
            <Kpi label="Последний парсинг" value={counts.lastParsed} />
            <Kpi label="Обновление базы" value={counts.lastUpdate} />
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
      <section className="card page-head">
        <h1>Скоро разместим информацию.</h1>
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
            <p className="muted">{cardsLoading ? 'Загружаю карточки...' : 'Ничего не найдено по вашим фильтрам'}</p>
          </div>
        )}
      </section>

      {hasMore ? (
        <div className="load-more-row">
          <button className="button ghost" onClick={() => loadCards(false)} disabled={cardsLoading}>
            {cardsLoading ? 'Загружаю...' : `Загрузить ещё ${PAGE_SIZE}`}
          </button>
        </div>
      ) : null}
    </div>
  )
}

function OfftopNewsPage({ signals, favorites = [], auth, onToggleFavorite }) {
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadOfftop = async (reset = false) => {
    const offset = reset ? 0 : items.length
    setLoading(true)
    setError('')
    if (reset) {
      setItems([])
      setHasMore(false)
    }
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
        hotness: '1',
        sort: 'time_desc',
      })
      if (query.trim()) params.set('q', query.trim())
      const data = await apiFetch(`/api/signals?${params.toString()}`)
      const nextItems = data.items || []
      setItems((prev) => reset ? nextItems : [...prev, ...nextItems])
      setHasMore(Boolean(data.has_more))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOfftop(true)
  }, [query])

  const submitSearch = (event) => {
    event.preventDefault()
    setQuery(searchInput.trim())
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Offtop News</h1>
        <p>Эти карточки убраны из общей вкладки и показываются здесь отдельно.</p>
        <form className="search-form" onSubmit={submitSearch}>
          <input
            className="search-input"
            placeholder="Поиск по всей базе offtop. Нажмите Enter для запуска."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <button className="button ghost" type="submit" disabled={loading}>
            Найти
          </button>
        </form>
      </section>

      {error ? (
        <section className="card center-card">
          <p className="muted">{error}</p>
        </section>
      ) : items.length ? (
        <section className="cards-grid">
          {items.map((item) => (
            <SignalCard
              key={item.id}
              item={item}
              auth={auth}
              onToggleFavorite={onToggleFavorite}
              favorite={favorites.some((fav) => fav.id === item.id)}
              offtop
            />
          ))}
        </section>
      ) : (
        <section className="card center-card">
          <h2>{loading ? 'Загружаю...' : 'Пока нет offtop-новостей'}</h2>
          <p>Когда такие карточки появятся, они будут отображаться здесь.</p>
        </section>
      )}

      {hasMore ? (
        <div className="load-more-row">
          <button className="button ghost" onClick={() => loadOfftop(false)} disabled={loading}>
            {loading ? 'Загружаю...' : `Загрузить ещё ${PAGE_SIZE}`}
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

  if (loading) return <div className="card">Загружаю карточку...</div>;
  if (!item) return <div className="card">{error || 'Карточка не найдена'}</div>;

  const sourceUrls = Array.isArray(item.source_urls) && item.source_urls.length
    ? item.source_urls.filter(Boolean)
    : [item.url].filter(Boolean);
  const favorite = favorites.some((fav) => fav.id === item.id)

  return (
    <section className="card detail-card">
      <div className="detail-head">
        <div>
          <span className={`pill ${categoryClass(item.category)}`}>{item.category}</span>
          <h1>{item.headline}</h1>
          <p>
            {formatDate(item.published_at || item.created_at)} · {sourceUrls.map(url => getDomain(url)).join(', ')}
          </p>
        </div>
        <div className="detail-buttons">
          <button className="button ghost" onClick={() => window.open(routeUrl(`/signals/${item.id}`), '_blank', 'noopener,noreferrer')}>
            Открыть в новой вкладке
          </button>
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
        <InfoCard title="Hotness" text={String(item.hotness)} />

        <div className="info-card sources-card">
          <h3>Источники</h3>
          <p className="muted source-hint">Кликабельные ссылки на исходные публикации</p>
          <SourceLinks item={{ ...item, source_urls: sourceUrls }} />
        </div>
      </div>
    </section>
  )
}

function SignalCard({ item, auth, onToggleFavorite, favorite = false, variant = 'default', offtop = false }) {
  const published = item.published_at || item.created_at

  const openInNewTab = () => {
    if (offtop && item.url) {
      window.open(item.url, '_blank', 'noopener,noreferrer')
      return
    }
    window.open(routeUrl(`/signals/${item.id}`), '_blank', 'noopener,noreferrer')
  }

  return (
    <article className={`signal-card variant-${variant} ${offtop ? 'is-offtop' : ''}`}>
      <div className="signal-top">
        <div className="signal-headline">
          {!offtop ? <span className={`pill ${categoryClass(item.category)}`}>{item.category}</span> : null}
          <h3>{item.headline}</h3>
        </div>
        {!offtop ? <span className={`hot-badge ${hotnessClass(item.hotness)}`}>Hotness {item.hotness}</span> : null}
      </div>

      {!offtop ? <div className="signal-meta">
        <span>{formatDate(published)}</span>
        <span>{item.source_name}</span>
      </div> : null}

      {!offtop && item.summary ? <p>{item.summary}</p> : null}
      {!offtop && item.why_now ? <p><b>Актуальность:</b> {item.why_now}</p> : null}

      {!offtop ? <SourceLinks item={item} compact /> : null}

      <div className="signal-actions">
        <button className="button ghost" onClick={openInNewTab}>Открыть</button>
        <button className="button icon-button ghost" title="Скопировать ссылку" onClick={() => copySignalLink(item.id)}>
          ⧉
        </button>
        <button className="button icon-button primary favorite-button" title={favorite ? 'Убрать из избранного' : 'В избранное'} onClick={() => onToggleFavorite?.(item.id)}>
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

function NotificationsPage({ auth, signals, notifications, settings, onSaveSettings, onClear }) {
  const [rules, setRules] = useState(settings.length ? settings : [{ theme: '', source_name: '', hotness_min: '' }])

  useEffect(() => {
    setRules(settings.length ? settings : [{ theme: '', source_name: '', hotness_min: '' }])
  }, [settings])

  const topicOptions = useMemo(() => {
    const values = new Set()
    ;(signals || []).forEach((item) => {
      if (item.category) values.add(item.category)
    })
    ;(rules || []).forEach((rule) => {
      if (rule.theme) values.add(rule.theme)
    })
    return [{ value: '', label: 'Любая тема' }, ...[...values].sort().map((value) => ({ value, label: value }))]
  }, [signals, rules])

  const sourceOptions = useMemo(() => {
    const values = new Set()
    ;(signals || []).forEach((item) => {
      if (item.source_name) values.add(item.source_name)
    })
    ;(rules || []).forEach((rule) => {
      if (rule.source_name) values.add(rule.source_name)
    })
    return [{ value: '', label: 'Любой источник' }, ...[...values].sort().map((value) => ({ value, label: value }))]
  }, [signals, rules])

  const hotnessOptions = [
    { value: '', label: 'Любой hotness' },
    { value: '5', label: 'от 5' },
    { value: '4', label: 'от 4' },
    { value: '3', label: 'от 3' },
    { value: '2', label: 'от 2' },
    { value: '1', label: 'от 1' }
  ];

  const addRule = () => {
    setRules((prev) => [...prev, { theme: '', source_name: '', hotness_min: '' }])
  }

  const updateRule = (index, patch) => {
    setRules((prev) => prev.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)))
  }

  const removeRule = (index) => {
    setRules((prev) => prev.filter((_, i) => i !== index))
  }

  const saveRules = async () => {
    const clean = rules
      .map((rule) => ({
        theme: rule.theme || '',
        source_name: rule.source_name || '',
        hotness_min: rule.hotness_min === '' ? '' : Number(rule.hotness_min),
      }))
      .filter((rule) => rule.theme || rule.source_name || rule.hotness_min !== '')

    await onSaveSettings(clean)
  }

  const openNotification = (item) => {
    if (item.signal_id) {
      window.open(routeUrl(`/signals/${item.signal_id}`), '_blank', 'noopener,noreferrer')
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
        <h1>Настройки уведомлений</h1>
        <p>Можно создать несколько независимых правил. Они не мешают друг другу.</p>
        <div className="hero-actions">
          <button className="button ghost" onClick={onClear}>Очистить уведомления</button>
        </div>
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <h2>Тема, источник и hotness</h2>
          </div>
          <button className="button ghost" onClick={addRule}>Добавить правило</button>
        </div>

        <div className="rules-list">
          {rules.map((rule, index) => (
            <div className="rule-row" key={index}>
              <CustomSelect
                value={rule.theme}
                options={topicOptions}
                onChange={(val) => updateRule(index, { theme: val })}
              />

              <CustomSelect
                value={rule.source_name}
                options={sourceOptions}
                onChange={(val) => updateRule(index, { source_name: val })}
              />

              <CustomSelect
                value={rule.hotness_min}
                options={hotnessOptions}
                onChange={(val) => updateRule(index, { hotness_min: val })}
              />

              <button className="button ghost" onClick={() => removeRule(index)}>Удалить</button>
            </div>
          ))}
        </div>

        <div className="hero-actions" style={{ marginTop: '20px' }}>
          <button className="button primary" onClick={saveRules}>Сохранить правила</button>
        </div>
      </section>

      <section className="cards-grid">
        {notifications.map((item) => (
          <button key={item.id} className="notification-card" onClick={() => openNotification(item)}>
            <div className="notification-title">{item.title}</div>
            <div className="notification-subtitle">{formatDate(item.created_at)}</div>
          </button>
        ))}
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

      <section className="card form-card">
        <h2>Редактирование профиля</h2>
        <form className="form-grid" onSubmit={save}>
          <label className="field">
            <span>ФИО</span>
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

function RegisterPage({ onAuth }) {
  const [step, setStep] = useState(1)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [promoCode, setPromoCode] = useState('')
  const [paid, setPaid] = useState(false)
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
      setNotice('Пользователь создан. Теперь оплати или введи промокод.')
    } catch (error) {
      setNotice(error.message)
    }
  }

  const openPay = () => {
    setPaid(true)
    setNotice('Оплата отмечена для демо-доступа.')
  }

  const activate = async (e) => {
    e.preventDefault()
    try {
      const data = await apiFetch('/api/activate', {
        method: 'POST',
        body: JSON.stringify({
          email,
          promo_code: promoCode,
          payment_success: paid,
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
        <h1>Сначала ФИО, почта, пароль</h1>
        <p>Потом уже активация через оплату или промокод.</p>
      </section>

      <section className="card form-card">
        {step === 1 ? (
          <form className="form-grid" onSubmit={register}>
            <label className="field">
              <span>ФИО</span>
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
            <div className="flash">Почта для активации: {email}</div>
            <label className="field">
              <span>Промокод</span>
              <input value={promoCode} onChange={(e) => setPromoCode(e.target.value)} />
            </label>
            <button className="button ghost full" type="button" onClick={openPay}>
              Оплатить
            </button>
            <button className="button primary full" type="submit">
              Активировать
            </button>
          </form>
        )}

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
      setNotice(error.message)
    }
  }

  return (
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
  )
}

function AdminUsersPage({ auth, users, refreshAdmin }) {
  const [current, setCurrent] = useState(null)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('user')
  const [activated, setActivated] = useState(false)
  const [notice, setNotice] = useState('')

  const handleForceUpdate = async () => {
    if (!window.confirm("Запустить принудительное обновление базы?")) return;
    try {
      const data = await apiFetch('/api/admin/update', {
        method: 'POST',
        body: JSON.stringify({}),
      }, auth.token)
      setNotice(updateMessage(data))
    } catch (err) {
      setNotice(updateErrorMessage(err))
    }
  };

  const openEdit = (user) => {
    setCurrent(user)
    setFullName(user.full_name)
    setEmail(user.email)
    setRole(user.role)
    setActivated(user.activated)
  }

  const save = async (e) => {
    e.preventDefault()
    if (!current) return
    try {
      await apiFetch(`/api/admin/users/${current.id}`, {
        method: 'PUT',
        body: JSON.stringify({ full_name: fullName, email, role, activated }),
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>Пользователи</h1>
            <p>Здесь можно редактировать роли и доступ.</p>
          </div>
          {/* ДОБАВЛЕННАЯ КНОПКА */}
          <button className="button primary" onClick={handleForceUpdate}>
            Обновить базу
          </button>
        </div>
      </section>

      <section className="grid-2">
        <div className="card table-wrap">
          <table className="market-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Имя</th>
                <th>Почта</th>
                <th>Роль</th>
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
                <span>ФИО</span>
                <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
              </label>
              <label className="field">
                <span>Почта</span>
                <input value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label className="field">
                <span>Роль</span>
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
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

function AdminPromosPage({ auth, promos, refreshAdmin }) {
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [notice, setNotice] = useState('')

  const addPromo = async (e) => {
    e.preventDefault()
    try {
      await apiFetch('/api/admin/promo-codes', {
        method: 'POST',
        body: JSON.stringify({ code, description }),
      }, auth.token)
      setCode('')
      setDescription('')
      setNotice('Промокод добавлен')
      await refreshAdmin(auth.token)
    } catch (error) {
      setNotice(error.message)
    }
  }

  const updatePromo = async (promo, patch) => {
    try {
      await apiFetch(`/api/admin/promo-codes/${promo.id}`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      }, auth.token)
      await refreshAdmin(auth.token)
    } catch (error) {
      setNotice(error.message)
    }
  }

  return (
    <div className="stack">
      <section className="card page-head">
        <h1>Промокоды</h1>
      </section>

      <section className="card form-card">
        <form className="promo-form" onSubmit={addPromo}>
          <input placeholder="Код" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
          <input placeholder="Описание" value={description} onChange={(e) => setDescription(e.target.value)} />
          <button className="button primary" type="submit">Добавить</button>
        </form>

        <div className="promo-list">
          {promos.map((promo) => (
            <div key={promo.id} className="promo-row">
              <input value={promo.code} onChange={(e) => updatePromo(promo, { code: e.target.value })} />
              <input value={promo.description || ''} onChange={(e) => updatePromo(promo, { description: e.target.value })} />
              <label className="promo-switch">
                <input type="checkbox" checked={promo.active} onChange={(e) => updatePromo(promo, { active: e.target.checked })} />
                active
              </label>
            </div>
          ))}
        </div>

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
