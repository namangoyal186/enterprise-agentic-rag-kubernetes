/**
 * Kubernetes Enterprise AI - High-Performance Frontend Engine
 * Vanilla JavaScript (Zero React Overhead, <2ms initialization)
 */

(function () {
  'use strict';

  // --- State ---
  let currentUser = null;
  let currentThreadId = null;
  let threads = [];
  let isGenerating = false;

  // --- DOM Elements ---
  const loginView = document.getElementById('login-view');
  const chatView = document.getElementById('chat-view');
  const sidebar = document.getElementById('sidebar');
  const newChatBtn = document.getElementById('new-chat-btn');
  const threadsList = document.getElementById('threads-list');

  const logoutBtn = document.getElementById('logout-btn');
  const userAvatar = document.getElementById('user-avatar');
  const userName = document.getElementById('user-name');
  const userEmail = document.getElementById('user-email');
  const currentThreadTitle = document.getElementById('current-thread-title');
  const messagesContainer = document.getElementById('messages-container');
  const chatForm = document.getElementById('chat-form');
  const promptInput = document.getElementById('prompt-input');
  const sendBtn = document.getElementById('send-btn');
  const emptyState = document.getElementById('empty-state');

  // Modal Elements
  const architectureModalBtn = document.getElementById('architecture-modal-btn');
  const architectureModal = document.getElementById('architecture-modal');
  const modalCloseBtn = document.getElementById('modal-close-btn');
  const modalTabs = document.querySelectorAll('.modal-tab');
  const tabContents = document.querySelectorAll('.tab-content');
  const healthBadgesContainer = document.getElementById('health-badges-container');
  const logfireExternalLink = document.getElementById('logfire-external-link');


  // --- Initialization ---


  async function init() {
    setupMarked();
    setupEventListeners();
    await checkAuth();
  }

  function setupMarked() {
    if (window.marked) {
      marked.setOptions({
        highlight: function (code, lang) {
          if (window.hljs && lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
          }
          return window.hljs ? hljs.highlightAuto(code).value : code;
        },
        breaks: true,
        gfm: true,
      });
    }
  }

  function setupEventListeners() {
    // Input Auto-resize & submit validation
    promptInput.addEventListener('input', () => {
      promptInput.style.height = 'auto';
      promptInput.style.height = Math.min(promptInput.scrollHeight, 180) + 'px';
      sendBtn.disabled = !promptInput.value.trim() || isGenerating;
    });

    promptInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) {
          handleChatSubmit();
        }
      }
    });

    // Chat Form Submit
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!sendBtn.disabled) {
        handleChatSubmit();
      }
    });

    // New Chat Button
    newChatBtn.addEventListener('click', () => {
      startNewChat();
    });

    // Logout Button
    logoutBtn.addEventListener('click', async () => {
      await logout();
    });

    // Sidebar Expand & Collapse Toggles (Desktop & Mobile)
    const sidebarExpandBtn = document.getElementById('sidebar-expand-btn');
    const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');

    if (sidebarExpandBtn) {
      sidebarExpandBtn.addEventListener('click', () => {
        if (window.innerWidth <= 768) {
          sidebar.classList.toggle('open');
        } else {
          sidebar.classList.toggle('collapsed');
        }
      });
    }

    if (sidebarCollapseBtn) {
      sidebarCollapseBtn.addEventListener('click', () => {
        if (window.innerWidth <= 768) {
          sidebar.classList.remove('open');
        } else {
          sidebar.classList.add('collapsed');
        }
      });
    }

    // Architecture & Telemetry Modal Listeners
    if (architectureModalBtn && architectureModal) {
      architectureModalBtn.addEventListener('click', () => {
        architectureModal.classList.remove('hidden');
        fetchSystemArchitecture();
      });
    }

    if (modalCloseBtn && architectureModal) {
      modalCloseBtn.addEventListener('click', () => {
        architectureModal.classList.add('hidden');
      });
    }

    if (architectureModal) {
      architectureModal.addEventListener('click', (e) => {
        if (e.target === architectureModal) {
          architectureModal.classList.add('hidden');
        }
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && architectureModal && !architectureModal.classList.contains('hidden')) {
        architectureModal.classList.add('hidden');
      }
    });

    // Tab Switching
    modalTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        modalTabs.forEach(t => t.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const target = document.getElementById(tab.dataset.tab);
        if (target) target.classList.add('active');
      });
    });

    // Trace Accordion Toggle in messages
    messagesContainer.addEventListener('click', (e) => {
      const traceHeader = e.target.closest('.trace-header');
      if (traceHeader) {
        const card = traceHeader.closest('.trace-card');
        if (card) {
          card.classList.toggle('open');
        }
      }
    });
  }



  // --- Authentication ---


  async function checkAuth() {
    // 1. Check URL parameters for session token or error
    const urlParams = new URLSearchParams(window.location.search);
    const sessionParam = urlParams.get('session');
    const errorParam = urlParams.get('error');

    if (errorParam) {
      console.error('OAuth Error:', errorParam);
    }

    if (sessionParam) {
      localStorage.setItem('kube_session', sessionParam);
      document.cookie = `kube_session=${sessionParam}; path=/; max-age=2592000; samesite=lax`;
      window.history.replaceState({}, '', window.location.pathname);
    }

    // 2. Query /auth/me with cookie and Authorization Bearer header fallback
    try {
      const storedToken = localStorage.getItem('kube_session');
      const headers = storedToken ? { 'Authorization': `Bearer ${storedToken}` } : {};
      const res = await fetch('/auth/me', { headers });
      if (res.ok) {
        const data = await res.json();
        if (data && data.user && data.user.user_id) {
          currentUser = data.user;
          renderAuthenticatedView();
          return;
        }
      }
    } catch (err) {
      console.warn('Auth check error:', err);
    }
    renderUnauthenticatedView();
  }

  function renderUnauthenticatedView() {
    loginView.classList.remove('hidden');
    chatView.classList.add('hidden');
  }

  function renderAuthenticatedView() {
    loginView.classList.add('hidden');
    chatView.classList.remove('hidden');

    // Populate User Profile
    userName.textContent = currentUser.name || 'User';
    userEmail.textContent = currentUser.email || '';
    if (currentUser.picture) {
      userAvatar.innerHTML = `<img src="${currentUser.picture}" alt="${currentUser.name}">`;
    } else {
      userAvatar.textContent = (currentUser.name || 'U')[0].toUpperCase();
    }

    loadUserThreads();
  }

  async function logout() {
    localStorage.removeItem('kube_session');
    document.cookie = 'kube_session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    try {
      await fetch('/auth/logout', { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
    window.location.reload();
  }


  // --- Threads Management ---
  async function loadUserThreads() {
    try {
      const res = await fetch(`/api/users/${currentUser.user_id}/threads`);
      if (res.ok) {
        const data = await res.json();
        threads = data.threads || [];
        renderThreadsList();

        if (threads.length > 0) {
          selectThread(threads[0].thread_id, threads[0].title);
        } else {
          startNewChat();
        }
      }
    } catch (e) {
      console.error('Failed to load chat threads:', e);
    }
  }

  function renderThreadsList() {
    threadsList.innerHTML = '';
    threads.forEach((t) => {
      const item = document.createElement('div');
      item.className = `thread-item ${t.thread_id === currentThreadId ? 'active' : ''}`;
      item.innerHTML = `
        <span class="thread-title-text" title="${escapeHtml(t.title || 'New Chat')}">
          ${t.thread_id === currentThreadId ? '📍' : '💬'} ${escapeHtml(t.title || 'New Chat')}
        </span>
        <button class="thread-del-btn" title="Delete chat" data-id="${t.thread_id}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
        </button>
      `;

      item.querySelector('.thread-title-text').addEventListener('click', () => {
        selectThread(t.thread_id, t.title);
        if (window.innerWidth <= 768) {
          sidebar.classList.remove('open');
        }
      });

      item.querySelector('.thread-del-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteThread(t.thread_id);
      });

      threadsList.appendChild(item);
    });
  }

  function startNewChat() {
    currentThreadId = generateUUID();
    currentThreadTitle.textContent = 'New Chat';
    messagesContainer.innerHTML = '';
    messagesContainer.appendChild(emptyState);
    emptyState.classList.remove('hidden');
    renderThreadsList();
    promptInput.focus();
  }

  async function selectThread(threadId, title) {
    currentThreadId = threadId;
    currentThreadTitle.textContent = title || 'New Chat';
    renderThreadsList();
    await loadThreadHistory(threadId);
  }

  async function deleteThread(threadId) {
    try {
      await fetch(`/api/threads/${threadId}?user_id=${currentUser.user_id}`, { method: 'DELETE' });
      threads = threads.filter((t) => t.thread_id !== threadId);
      renderThreadsList();

      if (currentThreadId === threadId) {
        if (threads.length > 0) {
          selectThread(threads[0].thread_id, threads[0].title);
        } else {
          startNewChat();
        }
      }
    } catch (e) {
      console.error('Failed to delete thread:', e);
    }
  }

  async function loadThreadHistory(threadId) {
    messagesContainer.innerHTML = '';
    try {
      const res = await fetch(`/api/threads/${threadId}/history`);
      if (res.ok) {
        const data = await res.json();
        const messages = data.messages || [];
        if (messages.length === 0) {
          messagesContainer.appendChild(emptyState);
          emptyState.classList.remove('hidden');
        } else {
          emptyState.classList.add('hidden');
          messages.forEach((m) => {
            appendMessage(m.role, m.content, m.thought_process, m.sources, false);
          });
          scrollToBottom();
        }
      }
    } catch (e) {
      console.error('Failed to load messages:', e);
    }
  }

  // --- Chat Execution ---
  async function handleChatSubmit() {
    const query = promptInput.value.trim();
    if (!query || isGenerating) return;

    // Reset input
    promptInput.value = '';
    promptInput.style.height = 'auto';
    sendBtn.disabled = true;
    isGenerating = true;

    emptyState.classList.add('hidden');

    // Append User Message
    appendMessage('user', query);
    scrollToBottom();

    // Create Assistant Placeholder with Sleek Typing Indicator
    const assistantRow = document.createElement('div');
    assistantRow.className = 'message-row assistant';
    assistantRow.innerHTML = `
      <div class="message-avatar">🤖</div>
      <div class="message-body">
        <div class="message-author">Kubernetes AI</div>
        <div class="message-content" id="active-message-content">
          <div class="typing-indicator">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    `;
    messagesContainer.appendChild(assistantRow);
    scrollToBottom();

    const messageContent = assistantRow.querySelector('#active-message-content');

    try {
      const payload = {
        q: query,
        thread_id: currentThreadId,
        user_id: currentUser.user_id,
      };

      const res = await fetch('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.message || data.detail || `HTTP ${res.status}`);
      }

      // Stream/Render Clean Final Answer (No internal chunks or raw traces shown)
      const rawAnswer = data.answer || data.response || 'No response generated.';
      const cleanAnswer = stripThinkTags(rawAnswer);
      messageContent.innerHTML = '';
      await streamText(messageContent, cleanAnswer);

      // Render Per-Message Execution Trace Accordion
      if (data.trace) {
        const traceWrapper = document.createElement('div');
        traceWrapper.innerHTML = renderTraceHtml(data.trace, data.sources);
        if (traceWrapper.firstElementChild) {
          assistantRow.querySelector('.message-body').appendChild(traceWrapper.firstElementChild);
          scrollToBottom();
        }
      }

      // Update Thread Title in Sidebar if it's the first query
      const existing = threads.find((t) => t.thread_id === currentThreadId);
      const cleanT = query.length > 35 ? query.substring(0, 32) + '...' : query;
      if (!existing) {
        threads.unshift({ thread_id: currentThreadId, title: cleanT });
        currentThreadTitle.textContent = cleanT;
        renderThreadsList();
      }

    } catch (err) {
      console.error('Query execution error:', err);
      messageContent.innerHTML = `<p style="color: var(--error);">❌ Execution Error: ${escapeHtml(err.message)}</p>`;
    } finally {
      isGenerating = false;
      sendBtn.disabled = !promptInput.value.trim();
      scrollToBottom();
    }
  }

  function appendMessage(role, content, thoughtProcess = null, sources = null) {
    const row = document.createElement('div');
    row.className = `message-row ${role}`;

    const cleanContent = stripThinkTags(content);
    const parsedHtml = window.marked ? marked.parse(cleanContent) : escapeHtml(cleanContent);

    let trace = null;
    if (thoughtProcess && typeof thoughtProcess === 'object' && thoughtProcess.trace) {
      trace = thoughtProcess.trace;
    }

    const traceHtml = role === 'assistant' && trace ? renderTraceHtml(trace, sources) : '';

    row.innerHTML = `
      <div class="message-avatar">${role === 'user' ? '👤' : '🤖'}</div>
      <div class="message-body">
        <div class="message-author">${role === 'user' ? (currentUser ? currentUser.name : 'You') : 'Kubernetes AI'}</div>
        <div class="message-content">${parsedHtml}</div>
        ${traceHtml}
      </div>
    `;

    messagesContainer.appendChild(row);
  }

  function renderTraceHtml(trace, sources) {
    if (!trace || !trace.steps || !trace.steps.length) return '';

    const stepsHtml = trace.steps.map((s) => {
      const isBlocked = s.status === 'BLOCKED';
      const badgeClass = isBlocked ? 'trace-badge-status blocked' : 'trace-badge-status';
      return `
        <div class="trace-step">
          <div class="trace-step-left">
            <span class="trace-step-icon">${s.icon || '⚡'}</span>
            <span class="trace-step-name">${escapeHtml(s.node)}</span>
            <span class="trace-step-detail">— ${escapeHtml(s.detail)}</span>
          </div>
          <div class="trace-step-right">
            <span class="${badgeClass}">${escapeHtml(s.status)}</span>
            <span class="trace-latency">${s.duration_ms || 0}ms</span>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="trace-card">
        <div class="trace-header">
          <div class="trace-header-left">
            <span>⚡</span>
            <span>Execution Trace (${trace.total_latency_s || '0.0'}s • ${trace.steps.length} steps)</span>
          </div>
          <svg class="trace-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </div>
        <div class="trace-list">
          ${stepsHtml}
        </div>
      </div>
    `;
  }

  async function streamText(element, fullText) {


    let current = '';
    const speed = fullText.length > 600 ? 1 : 4;
    for (let i = 0; i < fullText.length; i++) {
      current += fullText[i];
      if (i % 3 === 0 || i === fullText.length - 1) {
        element.innerHTML = (window.marked ? marked.parse(current) : escapeHtml(current)) + '<span class="typing-cursor">▌</span>';
        scrollToBottom();
        await sleep(speed);
      }
    }
    element.innerHTML = window.marked ? marked.parse(fullText) : escapeHtml(fullText);
  }

  // --- Utilities ---
  function stripThinkTags(text) {
    if (!text || typeof text !== 'string') return '';
    return text.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  async function fetchSystemArchitecture() {
    try {
      const res = await fetch('/api/system/architecture');
      if (!res.ok) return;
      const data = await res.json();

      // Update Clean Service Health Badges
      if (healthBadgesContainer && data.services_health) {
        const s = data.services_health;
        const isOk = (val) => Boolean(val && (val === 'connected' || String(val).startsWith('ok')));

        const services = [
          { name: 'Neon PostgreSQL', role: 'Durable Memory & LangGraph State', ok: isOk(s.postgres) },
          { name: 'Qdrant Vector Cloud', role: 'Hybrid Dense + Sparse Storage', ok: isOk(s.qdrant) },
          { name: 'Upstash Redis', role: 'Sliding-Window Rate Limiter', ok: isOk(s.redis) },
          { name: 'Jina AI API', role: 'Embeddings v3 & Reranker v2', ok: isOk(s.jina_embeddings) },
          { name: 'LLM Gateway', role: 'Qwen 2.5 27B / Google Gemini 2.5', ok: isOk(s.llm_gateway) },
        ];

        healthBadgesContainer.innerHTML = services.map((svc) => `
          <div class="health-badge-card">
            <div class="health-badge-left">
              <span class="badge-dot ${svc.ok ? 'green' : 'red'}"></span>
              <div>
                <div class="health-service-name">${escapeHtml(svc.name)}</div>
                <div class="health-service-role">${escapeHtml(svc.role)}</div>
              </div>
            </div>
            <div class="health-status-pill ${svc.ok ? 'online' : 'offline'}">
              ${svc.ok ? 'Operational' : 'Degraded'}
            </div>
          </div>
        `).join('');
      }
    } catch (err) {
      console.warn('Could not fetch architecture metadata:', err);
    }
  }


  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();



