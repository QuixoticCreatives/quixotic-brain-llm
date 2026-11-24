import { Component, ErrorInfo, ReactNode } from 'react';

/* QA 2026-11-24: one broken screen (the Translate crash of 14 Nov) left people with a blank white page and no way out.
   Now they see what happened and can reload; their chats are saved on the server. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('Quixotic AI screen error', error, info.componentStack); }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main role="alert" className="min-h-screen grid place-items-center p-5 bg-[var(--color-canvas)]">
        <div className="bg-white rounded-3xl shadow-lift p-8 w-full max-w-[420px] text-center">
          <h1 className="text-xl font-bold mb-2">Something went wrong on this screen</h1>
          <p className="text-muted mb-5">Your chats are saved. Reload the page to continue. If it happens again, tell your administrator what you were doing.</p>
          <button className="btn primary w-full !h-[46px]" onClick={() => location.reload()}>Reload Quixotic AI</button>
        </div>
      </main>
    );
  }
}
