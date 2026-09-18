import React from 'react'

// Ловит ошибки рендера, чтобы одна плохая строка или пустое поле в ответе не
// роняли весь интерфейс в белый экран: показывает сообщение и кнопку сброса.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('UI error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel" style={{ margin: 20 }}>
          <h3>Сторінку не вдалося показати</h3>
          <p className="muted">{String(this.state.error?.message || this.state.error)}</p>
          <button className="btn" onClick={() => this.setState({ error: null })}>
            Спробувати ще раз
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
