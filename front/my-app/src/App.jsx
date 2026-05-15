import React, { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'

const API = import.meta.env.VITE_API_URL ?? ''
const SIGNALS_PAGE_SIZE = 100

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

function routeUrl(path) {
  return `${window.location.origin}${window.location.pathname}#${path}`
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('ru-RU', {
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

function categoryClass(category) {
  const value = String(category || '').toLowerCase()

  if (value.includes('банк') || value.includes('bank')) return 'category-banking'
  if (value.includes('плат') || value.includes('pay')) return 'category-payments'
  if (value.includes('ux') || value.includes('механ')) return 'category-ux'
  if (value.includes('парт')) return 'category-partnership'
  if (value.includes('регул')) return 'category-regulation'
  if (value.includes('рынок')) return 'category-market'
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

function Market({ market }) {
  const data = Array.isArray(market) ? market : (market?.items || []);

  return (
    <div className="page">
      <section className="card page-head">
        <h1>Полная статистика MOEX</h1>
      </section>

      <div className="card" style={{ marginTop: '20px', overflowX: 'auto', padding: '0' }}>
        {data.length ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px' }}>
            <thead>
              <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
                <th style={thStyle}>Дата</th>
                <th style={thStyle}>ЦБ в листинге</th>
                <th style={thStyle}>Общий объем (₽)</th>
                <th style={thStyle}>Сделок</th>
                <th style={thStyle}>Лидер торгов</th>
                <th style={thStyle}>Объем лидера (₽)</th>
              </tr>
            </thead>
            <tbody>
              {data.map((item, index) => (
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
export default function App() {
  const [auth, setAuth] = useState(loadAuth())
  const [signals, setSignals] = useState([])
  const [market, setMarket] = useState([])
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
    const data = await apiFetch('/api/signals?limit=500')
    setSignals(data.items || [])
  }

  const refreshMarket = async () => {
    const data = await apiFetch('/api/market')
    setMarket(data.items || [])
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
    await Promise.all([refreshSignals(), refreshMarket()])
    if (auth?.token) {
      await refreshSession(auth.token)
      if (auth?.user?.role === 'admin') {
        await refreshAdmin(auth.token)
      }
    }
  }

  const runUpdate = async () => {
    setUpdating(true)
    try {
      const data = await apiFetch('/api/update', {
        method: 'POST',
        body: JSON.stringify({}),
      }, auth?.token)
      flash(data.update?.message || 'Обновление запущено')
    } catch (error) {
      flash(error.message)
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
    <Route path="/" element={<HomePage signals={signalCardList} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} onRunUpdate={runUpdate} updating={updating} />} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="/register" element={<RegisterPage onAuth={persistAuth} />} />
    <Route path="/login" element={<LoginPage onAuth={persistAuth} />} />

    {/* Защищенные страницы (только для авторизованных) */}
    <Route path="/cards" element={
      <ProtectedRoute auth={auth}>
        <CardsPage signals={signalCardList} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} />
      </ProtectedRoute>
    } />
    <Route path="/offtop-news" element={
      <ProtectedRoute auth={auth}>
        <OfftopNewsPage signals={signalCardList} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} />
      </ProtectedRoute>
    } />
    <Route path="/search" element={
      <ProtectedRoute auth={auth}>
        <SearchPage signals={signalCardList} favorites={favorites} auth={auth} onToggleFavorite={toggleFavorite} />
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
    ['/cards', 'Карточки'],
    ['/offtop-news', 'Offtop news'],
    ['/search', 'Поиск'],
    ['/moex', 'MOEX'],
    ['/notifications', 'Уведомления'],
  ]

  const isAdmin = auth?.user?.role === 'admin'

  if (isAdmin) {
    links.push(['/admin/users', 'Админ users'], ['/admin/promos', 'Админ promos'])
  }

  return (
    <header className="topbar">
      <div className="brand">
        <img src="/logoRedCat.png" alt="Red Cat" />
        <div>
          <div className="brand-title">Red Cat</div>
          <div className="brand-subtitle">Trendwatcher</div>
        </div>
      </div>

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

function HomePage({ signals, favorites = [], auth, onToggleFavorite, onRunUpdate, updating }) {
  const filteredSignals = useMemo(() =>
    signals.filter(s => Number(s.hotness) > 1),
    [signals]
  );

  const sorted = useMemo(
    () => [...filteredSignals].sort((a, b) => signalTime(b) - signalTime(a)),
    [filteredSignals],
  )

  const hot5 = sorted.filter((item) => Number(item.hotness) === 5).slice(0, 1)
  const hot4 = sorted.filter((item) => Number(item.hotness) === 4).slice(0, 2)
  const hot3 = sorted.filter((item) => Number(item.hotness) === 3).slice(0, 3)

  const counts = {
    total: signals.length,
    topics: new Set(signals.map((item) => item.category).filter(Boolean)).size,
    sources: new Set(signals.map((item) => item.source_name).filter(Boolean)).size,
    h5: signals.filter((item) => Number(item.hotness) === 5).length,
    h4: signals.filter((item) => Number(item.hotness) === 4).length,
    h3: signals.filter((item) => Number(item.hotness) === 3).length,
    h1: signals.filter((item) => Number(item.hotness) === 1).length,
  }

  return (
    <div className="stack">
      <section className="hero card">
        <div>
          <span className="eyebrow">Трендвотчер по финтех-публикациям</span>
          <h1>Готовые сигналы из базы, без лишнего шума</h1>
          <p>
            Все цифры считаются по базе карточек. На главной показываются только последние новости
            по hotness 5, 4 и 3.
          </p>
          <div className="hero-actions">
            <Link to="/cards" className="button primary">Открыть карточки</Link>
            <Link to="/search" className="button ghost">Открыть поиск</Link>
            {auth?.user?.role === 'admin' ? (
              <button className="button ghost" onClick={onRunUpdate} disabled={updating}>
                {updating ? 'Запускаю...' : 'Обновить базу'}
              </button>
            ) : null}
          </div>
        </div>

        <div className="hero-panel">
          <div className="kpi-grid">
            <Kpi label="Всего карточек" value={counts.total} />
            <Kpi label="Тем" value={counts.topics} />
            <Kpi label="Источников" value={counts.sources} />
            <Kpi label="Hotness 5" value={counts.h5} />
            <Kpi label="Hotness 4" value={counts.h4} />
            <Kpi label="Hotness 3" value={counts.h3} />
            <Kpi label="Hotness 1" value={counts.h1} />
          </div>
        </div>
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <span className="eyebrow">Последние новости</span>
            <h2>Показываем только свежие карточки</h2>
          </div>
          <Link to="/cards" className="button ghost">Все карточки</Link>
        </div>

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
      </section>
    </div>
  )
}

function AboutPage() {
  return (
    <div className="stack">
      <section className="card page-head">
        <span className="eyebrow">О проекте</span>
        <h1>Скоро разместим информацию.</h1>
      </section>
    </div>
  )
}

function SearchPage({ signals, favorites = [], auth, onToggleFavorite }) {
  const [query, setQuery] = useState('')

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()

    const list = (signals || []).filter((item) => Number(item.hotness) !== 1)

    if (!q) return list.slice(0, 12)

    return list.filter((item) => {
      return [
        item.headline,
        item.summary,
        item.why_now,
        item.category,
        item.source_name,
      ].join(' ').toLowerCase().includes(q)
    })
  }, [signals, query])

  return (
    <div className="stack">
      <section className="card search-window">
        <span className="eyebrow">Поиск карточек</span>
        <h1>Отдельное окно поиска</h1>
        <p>Поиск вынесен отдельно и не мешает вкладке «Карточки».</p>
        <input
          className="search-input"
          placeholder="Ищи по теме, источнику, заголовку..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </section>

      <section className="cards-grid">
        {results.map((item) => (
          <SignalCard
            key={item.id}
            item={item}
            auth={auth}
            onToggleFavorite={onToggleFavorite}
            favorite={favorites.some((fav) => fav.id === item.id)}
          />
        ))}
      </section>
    </div>
  )
}

function CardsPage({ signals, favorites = [], auth, onToggleFavorite }) {
  const [sortBy, setSortBy] = useState('time_desc')
  const [category, setCategory] = useState('all')
  const [source, setSource] = useState('all')
  const [hotness, setHotness] = useState('all')
  const [timeRange, setTimeRange] = useState('all')
  const [pageSignals, setPageSignals] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [cardsLoading, setCardsLoading] = useState(false)
  const [cardsError, setCardsError] = useState('')

  const buildCardsPath = (offset) => {
    const params = new URLSearchParams({
      limit: String(SIGNALS_PAGE_SIZE),
      offset: String(offset),
      sort: sortBy,
    })
    if (category !== 'all') params.set('category', category)
    if (source !== 'all') params.set('source', source)
    if (hotness !== 'all') params.set('hotness', hotness)
    if (timeRange !== 'all') params.set('time_range', timeRange)
    return `/api/signals?${params.toString()}`
  }

  const loadCards = async (reset = false) => {
    const offset = reset ? 0 : pageSignals.length
    setCardsLoading(true)
    setCardsError('')
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
  }, [sortBy, category, source, hotness, timeRange])

  const topics = useMemo(() => {
    const values = signals.filter((item) => Number(item.hotness) !== 1).map((item) => item.category).filter(Boolean)
    return ['all', ...new Set(values)]
  }, [signals])

  const sources = useMemo(() => {
    const values = signals.filter((item) => Number(item.hotness) !== 1).map((item) => item.source_name).filter(Boolean)
    return ['all', ...new Set(values)]
  }, [signals])

  const filtered = useMemo(() => {
    const now = Date.now()

    let items = pageSignals.filter((item) => Number(item.hotness) !== 1)

    items = items.filter((item) => {
      const byCategory = category === 'all' || item.category === category
      const bySource = source === 'all' || item.source_name === source
      const byHotness = hotness === 'all' || Number(item.hotness) === Number(hotness)

      const published = signalTime(item)
      const byTime =
        timeRange === 'all' ||
        (published > 0 && timeRange === 'day' && now - published <= 24 * 60 * 60 * 1000) ||
        (published > 0 && timeRange === 'week' && now - published <= 7 * 24 * 60 * 60 * 1000) ||
        (published > 0 && timeRange === 'month' && now - published <= 30 * 24 * 60 * 60 * 1000)

      return byCategory && bySource && byHotness && byTime
    })

    items = [...items].sort((a, b) => {
      const ta = signalTime(a)
      const tb = signalTime(b)

      if (sortBy === 'hotness') {
        return Number(b.hotness) - Number(a.hotness) || tb - ta
      }

      if (sortBy === 'time_asc') return ta - tb
      return tb - ta
    })

    return items
  }, [pageSignals, sortBy, category, source, hotness, timeRange])

  return (
    <div className="stack">
      {/* 1. Заголовок страницы */}
      <section className="card page-head">
        <span className="eyebrow">Карточки</span>
        <h1>Все карточки</h1>
        <p>Используйте фильтры ниже для сортировки и поиска по категориям.</p>

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

          <CustomSelect
            value={category}
            onChange={setCategory}
            options={topics.map(t => ({ value: t, label: t === 'all' ? 'Все темы' : t }))}
          />

          <CustomSelect
            value={source}
            onChange={setSource}
            options={sources.map(s => ({ value: s, label: s === 'all' ? 'Все источники' : s }))}
          />

          <CustomSelect
            value={hotness}
            onChange={setHotness}
            options={[
              { value: 'all', label: 'Любой hotness' },
              { value: '5', label: 'Hotness: 5' },
              { value: '4', label: 'Hotness: 4' },
              { value: '3', label: 'Hotness: 3' },
              { value: '2', label: 'Hotness: 2' }
            ]}
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
        ) : filtered.length > 0 ? (
          filtered.map((item) => (
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
            {cardsLoading ? 'Загружаю...' : `Загрузить ещё ${SIGNALS_PAGE_SIZE}`}
          </button>
        </div>
      ) : null}
    </div>
  )
}

function OfftopNewsPage({ signals, favorites = [], auth, onToggleFavorite }) {
  const offTop = useMemo(() => {
    return [...signals]
      .filter((item) => Number(item.hotness) === 1)
      .sort((a, b) => signalTime(b) - signalTime(a))
  }, [signals])

  return (
    <div className="stack">
      <section className="card page-head">
        <span className="eyebrow">Offtop news</span>
        <h1>Новости с hotness 1</h1>
        <p>Эти карточки убраны из общей вкладки и показываются здесь отдельно.</p>
      </section>

      {offTop.length ? (
        <section className="cards-grid">
          {offTop.map((item) => (
            <SignalCard
              key={item.id}
              item={item}
              auth={auth}
              onToggleFavorite={onToggleFavorite}
              favorite={favorites.some((fav) => fav.id === item.id)}
            />
          ))}
        </section>
      ) : (
        <section className="card center-card">
          <h2>Пока нет новостей с hotness 1</h2>
          <p>Когда такие карточки появятся, они будут отображаться здесь.</p>
        </section>
      )}
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
    ? item.source_urls.slice(0, 3)
    : [item.url];

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
          <button className="button primary" onClick={() => onToggleFavorite(item.id)}>
            {favorites.some((fav) => fav.id === item.id) ? 'Убрать из избранного' : 'В избранное'}
          </button>
        </div>
      </div>

      <div className="detail-grid">
        <InfoCard title="Summary" text={item.summary} />
        <InfoCard title="Why now" text={item.why_now} />
        <InfoCard title="Draft" text={item.draft} />
        <InfoCard title="Hotness" text={String(item.hotness)} />

        {/* Добавляем блок кликабельных источников (Пункт 5) */}
        <div className="info-card">
          <h3>Источники</h3>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
            {sourceUrls.filter(Boolean).map((url, idx) => (
              <a
                key={idx}
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="mini-pill"
                style={{ textDecoration: 'none', color: 'var(--primary)', border: '1px solid var(--primary)' }}
              >
                {getDomain(url)}
              </a>
            ))}
          </div>
        </div>
      </div>

      <div className="meta-row">
        {/* Здесь можно оставить теги/метки, если они приходят отдельно */}
        {(item.sources || []).map((source) => (
          <span key={source} className="mini-pill">{source}</span>
        ))}
      </div>
    </section>
  )
}

function SignalCard({ item, auth, onToggleFavorite, favorite = false, variant = 'default' }) {
  const published = item.published_at || item.created_at

  const openInNewTab = () => {
    window.open(routeUrl(`/signals/${item.id}`), '_blank', 'noopener,noreferrer')
  }

  return (
    <article className={`signal-card variant-${variant}`}>
      <div className="signal-top">
        <div className="signal-headline">
          <span className={`pill ${categoryClass(item.category)}`}>{item.category}</span>
          <h3>{item.headline}</h3>
        </div>
        <span className="hot-badge">Hotness {item.hotness}</span>
      </div>

      <div className="signal-meta">
        <span>{formatDate(published)}</span>
        <span>{item.source_name}</span>
      </div>

      <p><b>Summary:</b> {item.summary}</p>
      <p><b>Why now:</b> {item.why_now}</p>

      <div className="meta-row">
        {(item.sources || []).map((source) => (
          <span key={source} className="mini-pill">{source}</span>
        ))}
      </div>

      <div className="signal-actions">
        <button className="button ghost" onClick={openInNewTab}>Открыть</button>
        <button className="button primary" onClick={() => onToggleFavorite?.(item.id)}>
          {favorite ? 'Сохранено' : 'В избранное'}
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
        <span className="eyebrow">Сохранённые</span>
        <h1>Избранные карточки</h1>
        <p>Сюда складываются сигналы, которые пользователь сохранил.</p>
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
        <span className="eyebrow">Уведомления</span>
        <h1>Настройки уведомлений</h1>
        <p>Можно создать несколько независимых правил. Они не мешают друг другу.</p>
        <div className="hero-actions">
          <button className="button ghost" onClick={onClear}>Очистить уведомления</button>
        </div>
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <span className="eyebrow">Правила</span>
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
          <span className="eyebrow">{auth.user.role}</span>
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
        <span className="eyebrow">Регистрация</span>
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
        <span className="eyebrow">Вход</span>
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
      setNotice(data.update?.message || 'Обновление запущено')
    } catch (err) {
      setNotice(err.message)
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
            <span className="eyebrow">Админка</span>
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
        <span className="eyebrow">Админка</span>
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
  return (
    <div className="kpi">
      <div className="kpi-value">{value}</div>
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
