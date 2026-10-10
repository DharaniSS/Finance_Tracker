(function () {
  'use strict';

  const CURRENCY = 'INR';
  const state = { categories: [] };
  let selectedBudgetMonth;

  const dateOffset = (days) => {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  };

  const page = document.body.dataset.page;
  const money = (amount) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: CURRENCY, maximumFractionDigits: 2 }).format(Number(amount) || 0);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const categoryFor = (id) => state.categories.find((category) => category.id === id);
  const activeCategories = () => state.categories.filter((category) => !category.is_archived);
  const monthKey = (date) => String(date).slice(0, 7);
  const currentMonth = () => {
    const date = new Date();
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  };
  selectedBudgetMonth = currentMonth();

  function toast(message, type = 'success') {
    const region = document.getElementById('toast-region');
    if (!region) return;
    const item = document.createElement('div');
    item.className = `toast toast-${type}`;
    item.setAttribute('role', 'status');
    item.textContent = message;
    region.append(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  function csrfToken() {
    return document.querySelector('.logout-form input[name="csrf_token"]')?.value || '';
  }

  async function apiRequest(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    if (options.method && options.method !== 'GET') headers.set('X-CSRFToken', csrfToken());
    const response = await fetch(url, { ...options, headers, credentials: 'same-origin' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.error?.message || 'The request could not be completed.');
      error.fields = payload.error?.fields || {};
      if (response.status === 401) window.location.assign('/login.html');
      throw error;
    }
    return payload.data;
  }

  async function fetchApiCategories() {
    return apiRequest('/api/categories');
  }

  function apiCategoryOptions(select, categories, includeUncategorized = false) {
    if (!select) return;
    const options = categories.map((category) => ({ value: category.id, label: category.name }));
    if (includeUncategorized) options.unshift({ value: '', label: 'Uncategorized' });
    setSelectOptions(select, options, select.value);
  }

  function bindAuth() {
    document.querySelectorAll('[data-toggle-password]').forEach((button) => {
      button.addEventListener('click', () => {
        const input = document.getElementById(button.dataset.togglePassword);
        const visible = input.type === 'password';
        input.type = visible ? 'text' : 'password';
        button.textContent = visible ? 'Hide' : 'Show';
        button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} password`);
      });
    });
  }

  function bindShell() {
    document.querySelectorAll('[data-menu-toggle]').forEach((button) => button.addEventListener('click', () => {
      const sidebar = document.getElementById('sidebar');
      const open = sidebar.classList.toggle('sidebar-open');
      button.setAttribute('aria-expanded', String(open));
    }));
  }

  function setSelectOptions(select, options, selected) {
    if (!select) return;
    select.innerHTML = options.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join('');
    if (selected !== undefined) select.value = selected;
  }

  function formatDate(value) {
    const date = new Date(`${value}T12:00:00`);
    return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(date);
  }

  function renderBudgetProgress(rows) {
    const target = document.getElementById('budget-progress');
    if (!target) return;
    target.innerHTML = rows.length ? rows.map((item) => {
      const spent = Number(item.spent);
      const budget = Number(item.budget_amount);
      const percentage = item.percentage === null ? null : Number(item.percentage);
      const fill = percentage === null ? (spent > 0 ? 100 : 0) : Math.min(100, percentage);
      const status = item.status === 'exceeded' ? 'over' : item.status === 'warning' ? 'warning' : '';
      const color = /^#[\da-f]{6}$/i.test(item.category_color || '') ? item.category_color : '#768493';
      const caption = item.status === 'unbudgeted' ? 'No budget set' : `${percentage}% used${spent > budget ? ` · ${money(spent - budget)} over` : ''}`;
      return `<div class="budget-row"><div class="budget-row-heading"><span><i class="category-dot" style="--category-color:${color}"></i>${escapeHtml(item.category_name)}</span><span><strong>${money(spent)}</strong> <small>of ${money(budget)}</small></span></div><div class="progress-track" role="progressbar" aria-label="${escapeHtml(item.category_name)} budget used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${fill}"><span class="progress-fill ${status}" style="width:${fill}%;--category-color:${color}"></span></div><small class="budget-footnote">${caption}</small></div>`;
    }).join('') : '<div class="empty-inline">No categories yet. Create one to track a budget.</div>';
  }

  function renderAnomalyList(items) {
    const target = document.getElementById('anomaly-preview');
    if (!target) return;
    const reviewItems = items.filter((item) => item.is_anomaly || item.status === 'insufficient_history');
    target.innerHTML = reviewItems.length ? reviewItems.map((item) => {
      const flagged = item.is_anomaly;
      const action = flagged ? `<button class="button button-quiet button-small" type="button" data-ack-anomaly="${item.id}" ${item.acknowledged ? 'disabled' : ''}>${item.acknowledged ? 'Reviewed' : 'Mark reviewed'}</button>` : '';
      const confidence = item.confidence ? ` Confidence: ${Math.round(Number(item.confidence) * 100)}%.` : '';
      return `<div class="alert-item"><span class="alert-mark">${flagged ? '!' : '…'}</span><div class="alert-copy"><strong>${flagged ? 'Potential spending anomaly' : 'Insufficient history'}</strong><span>${escapeHtml(item.transaction.merchant)} · ${escapeHtml(item.transaction.category || 'Uncategorized')} · ${money(item.transaction.amount)}</span><small>${escapeHtml(item.explanation)}${confidence}${flagged ? ` Severity: ${escapeHtml(item.severity || 'unrated')}.` : ''}</small>${action}</div></div>`;
    }).join('') : '<div class="empty-inline">No analysis results for this month. Run an analysis to review your history.</div>';
  }

  function renderCharts(data) {
    if (typeof Plotly === 'undefined') return;
    const common = { paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: { family: 'DM Sans, sans-serif', color: '#c3cbd1', size: 11 }, margin: { l: 48, r: 14, t: 8, b: 32 }, xaxis: { gridcolor: 'rgba(255,255,255,.09)', zeroline: false, linecolor: 'rgba(255,255,255,.12)' }, yaxis: { gridcolor: 'rgba(255,255,255,.09)', zeroline: false, tickprefix: '₹', linecolor: 'transparent' }, showlegend: false };
    const daily = data.daily_spending;
    Plotly.react('trend-chart', [{ x: daily.map((item) => item.day), y: daily.map((item) => Number(item.amount)), type: 'scatter', mode: 'lines+markers', line: { color: '#f2b84b', width: 3, shape: 'spline' }, marker: { color: '#ffd77e', size: 5 }, fill: 'tozeroy', fillcolor: 'rgba(242,184,75,.13)', hovertemplate: 'Day %{x}<br>₹%{y:.2f}<extra></extra>' }], { ...common, xaxis: { ...common.xaxis, title: 'Day of month', dtick: Math.max(1, Math.ceil(daily.length / 8)) }, yaxis: { ...common.yaxis, rangemode: 'tozero' } }, { responsive: true, displayModeBar: false });

    const categories = data.category_spending;
    Plotly.react('category-chart', categories.length ? [{ labels: categories.map((item) => item.name), values: categories.map((item) => Number(item.amount)), type: 'pie', hole: 0.68, marker: { colors: categories.map((item) => /^#[\da-f]{6}$/i.test(item.color || '') ? item.color : '#768493'), line: { color: '#26313b', width: 3 } }, textinfo: 'none', hovertemplate: '%{label}<br>₹%{value:.2f} (%{percent})<extra></extra>' }] : [], { ...common, margin: { l: 8, r: 8, t: 4, b: 4 }, showlegend: categories.length > 0, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: '#c3cbd1' } }, annotations: categories.length ? [] : [{ text: 'No spending yet', showarrow: false, font: { color: '#b6c0c8', size: 13 } }] }, { responsive: true, displayModeBar: false });

    const months = data.monthly_spending;
    Plotly.react('monthly-chart', [{ x: months.map((item) => new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit' }).format(new Date(`${item.month}-01T12:00:00`))), y: months.map((item) => Number(item.amount)), type: 'bar', marker: { color: months.map((item) => item.month === data.month ? '#f2b84b' : 'rgba(212,225,235,.3)'), line: { color: months.map((item) => item.month === data.month ? '#f7ca70' : 'rgba(212,225,235,.24)'), width: 1 }, cornerradius: 4 }, hovertemplate: '%{x}<br>₹%{y:.2f}<extra></extra>' }], { ...common, bargap: 0.42, yaxis: { ...common.yaxis, rangemode: 'tozero' } }, { responsive: true, displayModeBar: false });

    const budgets = data.budget_vs_actual;
    Plotly.react('budget-chart', budgets.length ? [{ x: budgets.map((item) => item.category_name), y: budgets.map((item) => Number(item.budget_amount)), type: 'bar', name: 'Budget', marker: { color: 'rgba(212,225,235,.3)' }, hovertemplate: '%{x}<br>Budget ₹%{y:.2f}<extra></extra>' }, { x: budgets.map((item) => item.category_name), y: budgets.map((item) => Number(item.spent)), type: 'bar', name: 'Actual', marker: { color: '#f2b84b' }, hovertemplate: '%{x}<br>Spent ₹%{y:.2f}<extra></extra>' }] : [], { ...common, barmode: 'group', yaxis: { ...common.yaxis, rangemode: 'tozero' }, showlegend: budgets.length > 0, legend: { orientation: 'h', y: 1.12, font: { size: 10, color: '#c3cbd1' } }, annotations: budgets.length ? [] : [{ text: 'No budgets for this month', showarrow: false, font: { color: '#b6c0c8', size: 13 } }] }, { responsive: true, displayModeBar: false });
  }

  async function loadDashboard(month) {
    const status = document.getElementById('dashboard-feedback');
    status.textContent = 'Loading dashboard…';
    try {
      const data = await apiRequest(`/api/dashboard?month=${encodeURIComponent(month)}`);
      renderDashboard(data);
      status.textContent = '';
    } catch (error) {
      status.textContent = error.message || 'Dashboard data could not be loaded.';
    }
  }

  function renderDashboard(data) {
    const summary = data.summary;
    document.getElementById('summary-spent').textContent = money(summary.total_spent);
    document.getElementById('summary-period').textContent = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(`${data.month}-01T12:00:00`));
    document.getElementById('summary-count').textContent = summary.transaction_count;
    document.getElementById('summary-remaining').textContent = money(summary.budget_remaining);
    document.getElementById('summary-change').textContent = money(summary.change_amount);
    document.getElementById('summary-change-detail').textContent = summary.change_percent === null ? 'No previous-month spending to compare' : `${summary.change_percent}% versus previous month`;
    document.getElementById('summary-warning-count').textContent = summary.budget_warning_count;
    document.getElementById('summary-anomaly-count').textContent = summary.anomaly_count;
    document.getElementById('summary-attention').textContent = summary.budget_warning_count + summary.anomaly_count;
    renderBudgetProgress(data.budget_vs_actual);
    renderAnomalyList(data.anomalies);

    const recentBody = document.getElementById('recent-transactions');
    recentBody.innerHTML = data.recent_transactions.map((transaction) => {
      const color = /^#[\da-f]{6}$/i.test(transaction.category?.color || '') ? transaction.category.color : '#768493';
      return `<tr><td><span class="merchant-cell"><i class="category-dot" style="--category-color:${color}"></i><strong>${escapeHtml(transaction.merchant)}</strong></span></td><td>${escapeHtml(transaction.category?.name || 'Uncategorized')}</td><td>${formatDate(transaction.date)}</td><td class="align-right amount-cell">${money(transaction.amount)}</td></tr>`;
    }).join('');
    const empty = document.getElementById('recent-empty');
    empty.classList.toggle('hidden', data.recent_transactions.length > 0);
    document.querySelector('.table-panel .table-wrap').classList.toggle('hidden', data.recent_transactions.length === 0);
    renderCharts(data);
  }

  function initDashboardFilters() {
    if (page !== 'dashboard') return;
    const month = document.getElementById('month-filter');
    const year = document.getElementById('year-filter');
    const load = () => loadDashboard(`${year.value}-${month.value}`);
    (async () => {
      const status = document.getElementById('dashboard-feedback');
      status.textContent = 'Loading dashboard…';
      try {
        const initial = await apiRequest(`/api/dashboard?month=${currentMonth()}`);
        const options = initial.available_months;
        const monthOptions = Array.from({ length: 12 }, (_, index) => {
          const value = String(index + 1).padStart(2, '0');
          return { value, label: new Intl.DateTimeFormat('en-US', { month: 'long' }).format(new Date(`2000-${value}-01T12:00:00`)) };
        });
        setSelectOptions(month, monthOptions, currentMonth().slice(5));
        const years = [...new Set(options.map((value) => value.slice(0, 4)))].reverse();
        setSelectOptions(year, years.map((value) => ({ value, label: value })), currentMonth().slice(0, 4));
        month.addEventListener('change', load);
        year.addEventListener('change', load);
        renderDashboard(initial);
        status.textContent = '';

        document.getElementById('analyze-spending').addEventListener('click', async (event) => {
          const button = event.currentTarget;
          const feedback = document.getElementById('anomaly-feedback');
          button.disabled = true;
          feedback.textContent = 'Comparing transactions with earlier category history…';
          try {
            await apiRequest(`/api/anomalies/analyze?month=${encodeURIComponent(`${year.value}-${month.value}`)}`, { method: 'POST' });
            await loadDashboard(`${year.value}-${month.value}`);
            feedback.textContent = 'Analysis complete. Indicators are suggestions to review, not fraud determinations.';
          } catch (error) {
            feedback.textContent = error.message;
          } finally {
            button.disabled = false;
          }
        });

        document.getElementById('anomaly-preview').addEventListener('click', async (event) => {
          const button = event.target.closest('[data-ack-anomaly]');
          if (!button || button.disabled) return;
          button.disabled = true;
          try {
            await apiRequest(`/api/anomalies/${encodeURIComponent(button.dataset.ackAnomaly)}/acknowledge`, { method: 'POST' });
            await loadDashboard(`${year.value}-${month.value}`);
            toast('Anomaly marked as reviewed.');
          } catch (error) {
            document.getElementById('anomaly-feedback').textContent = error.message;
            button.disabled = false;
          }
        });
      } catch (error) {
        status.textContent = error.message || 'Dashboard data could not be loaded.';
      }
    })();
  }

  function updateCategoryOptions() {
    const select = document.getElementById('entry-category');
    if (select) {
      const options = activeCategories();
      setSelectOptions(select, options.map((category) => ({ value: category.id, label: category.name })), options[0]?.id || '');
    }
  }

  function initTransactionForm() {
    const form = document.getElementById('transaction-form');
    if (!form) return;
    const dateInput = document.getElementById('entry-date');
    dateInput.value = dateOffset(0);
    const saveButton = document.getElementById('save-transaction');
    const error = document.getElementById('transaction-error');
    const idInput = document.getElementById('transaction-id');
    saveButton.disabled = true;
    error.textContent = 'Loading your categories…';
    const params = new URLSearchParams(window.location.search);
    (async () => {
      try {
        const categories = await fetchApiCategories();
        apiCategoryOptions(document.getElementById('entry-category'), categories, true);
        if (params.has('edit')) {
          const transaction = await apiRequest(`/api/transactions/${encodeURIComponent(params.get('edit'))}`);
          populateTransactionForm(transaction);
        }
        error.textContent = '';
      } catch (requestError) {
        error.textContent = requestError.message;
      } finally {
        saveButton.disabled = false;
      }
    })();
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const id = idInput.value;
      const merchant = document.getElementById('entry-merchant').value.trim();
      const amount = document.getElementById('entry-amount').value.trim();
      const categoryId = document.getElementById('entry-category').value;
      const date = dateInput.value;
      const description = document.getElementById('entry-description').value.trim();
      if (!date || !merchant || !amount) {
        error.textContent = 'Enter a date, merchant, and positive amount.';
        return;
      }
      const payload = { merchant, amount, date, description, category_id: categoryId || null };
      const editing = Boolean(id);
      saveButton.disabled = true;
      saveButton.textContent = editing ? 'Saving…' : 'Adding…';
      error.textContent = '';
      try {
        await apiRequest(editing ? `/api/transactions/${encodeURIComponent(id)}` : '/api/transactions', {
          method: editing ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
        });
        form.reset();
        dateInput.value = dateOffset(0);
        idInput.value = '';
        setEntryMode(false);
        window.location.href = editing ? 'transactions.html?updated=1' : 'transactions.html?created=1';
      } catch (requestError) {
        error.textContent = Object.values(requestError.fields || {}).join(' ') || requestError.message;
      } finally {
        saveButton.disabled = false;
        saveButton.textContent = idInput.value ? 'Save changes' : 'Save transaction';
      }
    });
    document.getElementById('cancel-edit').addEventListener('click', () => { form.reset(); dateInput.value = dateOffset(0); setEntryMode(false); });
  }

  function populateTransactionForm(transaction) {
    document.getElementById('transaction-id').value = transaction.id;
    document.getElementById('entry-date').value = transaction.date;
    document.getElementById('entry-merchant').value = transaction.merchant;
    document.getElementById('entry-amount').value = transaction.amount;
    document.getElementById('entry-category').value = transaction.category_id ?? '';
    document.getElementById('entry-description').value = transaction.description || '';
    setEntryMode(true);
    document.getElementById('manual-entry').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function setEntryMode(editing) {
    document.getElementById('entry-heading').textContent = editing ? 'Edit transaction' : 'Add a transaction';
    document.getElementById('save-transaction').textContent = editing ? 'Save changes' : 'Save transaction';
    document.getElementById('cancel-edit').classList.toggle('hidden', !editing);
  }

  function initCsvImport() {
    const input = document.getElementById('csv-file');
    if (!input) return;
    const zone = document.getElementById('csv-dropzone');
    const previewWrap = document.getElementById('csv-preview-wrap');
    const previewButton = document.getElementById('import-valid-rows');
    const cancelButton = document.getElementById('cancel-csv-import');
    let previewId = null;

    async function cancelPreview() {
      if (!previewId) return;
      try {
        await apiRequest(`/api/transactions/import/preview/${encodeURIComponent(previewId)}`, { method: 'DELETE' });
      } catch (error) {
        document.getElementById('csv-feedback').textContent = error.message;
      }
      previewId = null;
    }

    const loadFile = async (file) => {
      if (!file) return;
      await cancelPreview();
      previewWrap.classList.add('hidden');
      if (!file.name.toLowerCase().endsWith('.csv')) {
        document.getElementById('csv-feedback').textContent = 'Choose a .csv file to continue.';
        return;
      }
      if (file.size > 1000000) {
        document.getElementById('csv-feedback').textContent = 'The upload exceeds the 1 MB file limit.';
        return;
      }
      document.getElementById('csv-feedback').textContent = 'Uploading and validating CSV…';
      previewButton.disabled = true;
      cancelButton.classList.add('hidden');
      try {
        const formData = new FormData();
        formData.append('file', file);
        const result = await apiRequest('/api/transactions/import/preview', { method: 'POST', body: formData });
        previewId = result.preview_id;
        renderCsvPreview(result.rows);
        document.getElementById('csv-feedback').textContent = `${file.name} validated. Review the rows before importing.`;
        cancelButton.classList.remove('hidden');
      } catch (requestError) {
        document.getElementById('csv-feedback').textContent = requestError.message;
        input.value = '';
      } finally {
        previewButton.disabled = false;
      }
    };
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
    input.addEventListener('change', () => loadFile(input.files[0]));
    ['dragenter', 'dragover'].forEach((name) => zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add('dropzone-active'); }));
    ['dragleave', 'drop'].forEach((name) => zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.remove('dropzone-active'); }));
    zone.addEventListener('drop', (event) => loadFile(event.dataTransfer.files[0]));
    previewButton.addEventListener('click', async () => {
      if (!previewId || previewButton.disabled) return;
      previewButton.disabled = true;
      previewButton.textContent = 'Importing…';
      try {
        const result = await apiRequest('/api/transactions/import/confirm', {
          method: 'POST',
          body: JSON.stringify({ preview_id: previewId }),
        });
        previewId = null;
        window.location.href = `transactions.html?imported=${result.imported_count}`;
      } catch (error) {
        document.getElementById('csv-feedback').textContent = error.message;
        previewButton.disabled = false;
        previewButton.textContent = 'Import valid rows';
      }
    });
    cancelButton.addEventListener('click', async () => {
      await cancelPreview();
      previewWrap.classList.add('hidden');
      input.value = '';
      document.getElementById('csv-feedback').textContent = 'Import cancelled. No transactions were saved.';
    });
  }

  function renderCsvPreview(rows) {
    const wrap = document.getElementById('csv-preview-wrap');
    wrap.classList.remove('hidden');
    const valid = rows.filter((row) => row.valid).length;
    const invalid = rows.length - valid;
    document.getElementById('csv-preview-summary').textContent = `${valid} valid · ${invalid} invalid. Invalid rows will not be imported. Dates must use YYYY-MM-DD; amounts must be positive.`;
    document.getElementById('csv-errors').innerHTML = rows.filter((row) => !row.valid).map((row) => `<div class="validation-message"><strong>Row ${row.row}:</strong> ${escapeHtml(row.errors.join(' · '))}</div>`).join('');
    document.getElementById('csv-preview-body').innerHTML = rows.map((row) => {
      const transaction = row.transaction;
      return `<tr><td>${row.row}</td><td>${escapeHtml(transaction.date || '—')}</td><td>${escapeHtml(transaction.merchant || '—')}</td><td>${escapeHtml(transaction.category || '—')}</td><td class="align-right">${escapeHtml(transaction.amount || '—')}</td><td><span class="status-pill ${row.valid ? 'status-ready' : 'status-invalid'}">${row.valid ? 'Valid' : 'Invalid'}</span></td></tr>`;
    }).join('');
    const button = document.getElementById('import-valid-rows');
    button.textContent = `Import ${valid} valid row${valid === 1 ? '' : 's'}`;
    button.disabled = valid === 0;
  }

  function initTransactions() {
    const body = document.getElementById('transactions-body');
    if (!body) return;
    const search = document.getElementById('transaction-search');
    const categoryFilter = document.getElementById('transaction-category-filter');
    const monthFilter = document.getElementById('transaction-month-filter');
    const feedback = document.getElementById('transactions-feedback');
    let transactions = [];
    const render = () => {
      const query = search.value.trim().toLowerCase();
      const selectedCategory = categoryFilter.value;
      const selectedMonth = monthFilter.value;
      const filtered = [...transactions].sort((a, b) => b.date.localeCompare(a.date)).filter((transaction) => {
        const textMatch = `${transaction.merchant} ${transaction.description || ''}`.toLowerCase().includes(query);
        return textMatch && (!selectedCategory || String(transaction.category_id) === selectedCategory) && (!selectedMonth || monthKey(transaction.date) === selectedMonth);
      });
      body.innerHTML = filtered.map((transaction) => {
        const category = transaction.category;
        const color = /^#[\da-f]{6}$/i.test(category?.color || '') ? category.color : '#768493';
        return `<tr><td><span class="merchant-cell"><i class="category-dot" style="--category-color:${color}"></i><strong>${escapeHtml(transaction.merchant)}</strong></span></td><td>${escapeHtml(category?.name || 'Uncategorized')}</td><td>${formatDate(transaction.date)}, ${transaction.date.slice(0, 4)}</td><td class="description-cell">${escapeHtml(transaction.description || '—')}</td><td class="align-right amount-cell">${money(transaction.amount)}</td><td class="action-cell"><a class="icon-button table-action" href="expenses.html?edit=${encodeURIComponent(transaction.id)}#manual-entry" aria-label="Edit ${escapeHtml(transaction.merchant)}">✎</a><button class="icon-button table-action delete-transaction" type="button" data-delete-transaction="${escapeHtml(transaction.id)}" aria-label="Delete ${escapeHtml(transaction.merchant)}">×</button></td></tr>`;
      }).join('');
      document.getElementById('transactions-empty').classList.toggle('hidden', filtered.length > 0);
      document.querySelector('.table-panel .table-wrap').classList.toggle('hidden', filtered.length === 0);
    };
    [search, categoryFilter, monthFilter].forEach((control) => control.addEventListener('input', render));
    body.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-delete-transaction]');
      if (!button) return;
      const transaction = transactions.find((item) => String(item.id) === button.dataset.deleteTransaction);
      if (!transaction || !window.confirm(`Delete the ${transaction.merchant} transaction?`)) return;
      button.disabled = true;
      try {
        await apiRequest(`/api/transactions/${encodeURIComponent(transaction.id)}`, { method: 'DELETE' });
        await loadTransactions();
        toast('Transaction deleted.');
      } catch (error) {
        feedback.textContent = error.message;
        button.disabled = false;
      }
    });

    async function loadTransactions() {
      feedback.textContent = 'Loading transactions…';
      try {
        const [data, categories] = await Promise.all([
          apiRequest('/api/transactions'),
          fetchApiCategories(),
        ]);
        transactions = data;
        apiCategoryOptions(categoryFilter, [{ id: '', name: 'All categories' }, ...categories]);
        body.innerHTML = '';
        document.querySelector('.table-panel .table-wrap').classList.remove('hidden');
        feedback.textContent = '';
        render();
        const params = new URLSearchParams(window.location.search);
        if (params.has('created') || params.has('updated') || params.has('imported')) {
          const message = params.has('created') ? 'Transaction added.' : params.has('updated') ? 'Transaction updated.' : `${params.get('imported')} transactions imported.`;
          toast(message);
          history.replaceState(null, '', window.location.pathname);
        }
      } catch (error) {
        feedback.textContent = error.message || 'Transactions could not be loaded.';
        document.querySelector('.table-panel .table-wrap').classList.add('hidden');
        document.getElementById('transactions-empty').classList.add('hidden');
      }
    }

    loadTransactions();
  }

  let categoryView = 'active';
  let budgetRows = [];

  function categoryBudget(categoryId) {
    return budgetRows.find((row) => row.category_id === categoryId);
  }

  function renderCategories() {
    const target = document.getElementById('category-list');
    if (!target) return;
    const archived = categoryView === 'archived';
    const items = state.categories.filter((category) => Boolean(category.is_archived) === archived);
    document.getElementById('category-count').textContent = `${items.length} ${categoryView} categor${items.length === 1 ? 'y' : 'ies'}`;
    target.innerHTML = items.length ? items.map((category) => {
      const budget = categoryBudget(category.id);
      const spent = Number(budget?.spent || 0);
      const budgetAmount = Number(budget?.budget_amount || 0);
      const percentage = budget?.percentage === null || !budget ? null : Number(budget.percentage);
      const fill = percentage === null ? (spent > 0 ? 100 : 0) : Math.min(100, percentage);
      const status = budget?.status === 'exceeded' ? 'over' : budget?.status === 'warning' ? 'warning' : '';
      const color = /^#[\da-f]{6}$/i.test(category.color || '') ? category.color : '#768493';
      const budgetCaption = budget?.status === 'unbudgeted' ? 'No budget set' : `${percentage}% used`;
      return `<article class="category-card"><div class="category-card-top"><span class="category-identity"><i class="category-swatch" style="--category-color:${color}"></i><strong>${escapeHtml(category.name)}</strong></span><div class="category-actions"><button class="icon-button table-action" type="button" data-edit-category="${category.id}" aria-label="Edit ${escapeHtml(category.name)}">✎</button><button class="button button-quiet button-small" type="button" data-toggle-category="${category.id}">${archived ? 'Reactivate' : 'Archive'}</button></div></div><div class="category-budget-line"><span>${escapeHtml(selectedBudgetMonth)} budget</span><strong>${money(budgetAmount)}</strong></div><div class="progress-track" role="progressbar" aria-label="${escapeHtml(category.name)} budget used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${fill}"><span class="progress-fill ${status}" style="width:${fill}%;--category-color:${color}"></span></div><small class="category-spend-caption">${money(spent)} spent · ${budgetCaption}${archived ? ' · archived' : ''}</small></article>`;
    }).join('') : `<div class="empty-state"><span class="empty-symbol">◷</span><strong>No ${categoryView} categories</strong><span>${archived ? 'Archived categories and their transaction history appear here.' : 'Create a category to organize transactions and budgets.'}</span></div>`;
  }

  async function loadCategories() {
    const feedback = document.getElementById('categories-feedback');
    feedback.textContent = 'Loading categories and budgets…';
    try {
      const [categories, budgets] = await Promise.all([
        apiRequest('/api/categories?status=all'),
        apiRequest(`/api/budgets?month=${encodeURIComponent(selectedBudgetMonth)}`),
      ]);
      state.categories = categories;
      budgetRows = budgets;
      renderCategories();
      updateCategoryOptions();
      feedback.textContent = '';
    } catch (error) {
      feedback.textContent = error.message || 'Categories could not be loaded.';
    }
  }

  function resetCategoryForm() {
    const form = document.getElementById('category-form');
    form.reset();
    document.getElementById('category-id').value = '';
    document.getElementById('category-form-title').textContent = 'Create a category';
    document.getElementById('save-category').textContent = 'Add category';
    document.getElementById('cancel-category-edit').classList.add('hidden');
    document.getElementById('category-error').textContent = '';
    document.getElementById('warning-threshold').value = 80;
    document.getElementById('threshold-value').value = '80%';
  }

  function initCategories() {
    const form = document.getElementById('category-form');
    if (!form) return;
    const monthInput = document.getElementById('budget-month');
    monthInput.value = selectedBudgetMonth;
    monthInput.addEventListener('change', () => {
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(monthInput.value)) return;
      selectedBudgetMonth = monthInput.value;
      loadCategories();
    });
    loadCategories();

    document.querySelectorAll('[data-category-view]').forEach((button) => button.addEventListener('click', () => {
      categoryView = button.dataset.categoryView;
      document.querySelectorAll('[data-category-view]').forEach((item) => {
        const active = item === button;
        item.classList.toggle('active', active);
        item.setAttribute('aria-pressed', String(active));
      });
      renderCategories();
    }));

    document.getElementById('warning-threshold').addEventListener('input', (event) => {
      document.getElementById('threshold-value').value = `${event.target.value}%`;
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const id = document.getElementById('category-id').value;
      const name = document.getElementById('category-name').value.trim();
      const budgetAmount = document.getElementById('category-budget').value.trim();
      const categoryError = document.getElementById('category-error');
      const saveButton = document.getElementById('save-category');
      if (!name || budgetAmount === '') {
        categoryError.textContent = 'Enter a category name and a budget amount for the selected month.';
        return;
      }
      saveButton.disabled = true;
      categoryError.textContent = '';
      const categoryPayload = {
        name,
        color: document.getElementById('category-color').value,
        warning_threshold: Number(document.getElementById('warning-threshold').value),
      };
      try {
        const category = await apiRequest(id ? `/api/categories/${encodeURIComponent(id)}` : '/api/categories', {
          method: id ? 'PATCH' : 'POST',
          body: JSON.stringify(categoryPayload),
        });
        if (!id) {
          document.getElementById('category-id').value = category.id;
          document.getElementById('category-form-title').textContent = 'Finish category budget';
          document.getElementById('save-category').textContent = 'Save monthly budget';
          document.getElementById('cancel-category-edit').classList.remove('hidden');
          await loadCategories();
        }
        const [year, month] = selectedBudgetMonth.split('-').map(Number);
        const existingBudget = budgetRows.find((item) => item.category_id === category.id);
        if (existingBudget) {
          await apiRequest(`/api/budgets/${existingBudget.budget_id}`, {
            method: 'PATCH',
            body: JSON.stringify({ budget_amount: budgetAmount }),
          });
        } else {
          await apiRequest('/api/budgets', {
            method: 'POST',
            body: JSON.stringify({ category_id: category.id, year, month, budget_amount: budgetAmount }),
          });
        }
        await loadCategories();
        toast(id ? 'Category and budget updated.' : 'Category created with a monthly budget.');
        resetCategoryForm();
      } catch (error) {
        categoryError.textContent = Object.values(error.fields || {}).join(' ') || error.message;
      } finally {
        saveButton.disabled = false;
      }
    });

    document.getElementById('cancel-category-edit').addEventListener('click', resetCategoryForm);
    document.getElementById('category-list').addEventListener('click', async (event) => {
      const edit = event.target.closest('[data-edit-category]');
      const toggle = event.target.closest('[data-toggle-category]');
      if (edit) {
        const category = state.categories.find((item) => item.id === Number(edit.dataset.editCategory));
        if (!category) return;
        const budget = categoryBudget(category.id);
        document.getElementById('category-id').value = category.id;
        document.getElementById('category-name').value = category.name;
        document.getElementById('category-budget').value = budget?.budget_amount ?? '0.00';
        document.getElementById('category-color').value = category.color || '#768493';
        document.getElementById('warning-threshold').value = category.warning_threshold;
        document.getElementById('threshold-value').value = `${category.warning_threshold}%`;
        document.getElementById('category-form-title').textContent = 'Edit category';
        document.getElementById('save-category').textContent = 'Save changes';
        document.getElementById('cancel-category-edit').classList.remove('hidden');
        document.getElementById('category-name').focus();
      }
      if (toggle) {
        const category = state.categories.find((item) => item.id === Number(toggle.dataset.toggleCategory));
        if (!category || toggle.disabled) return;
        toggle.disabled = true;
        try {
          await apiRequest(`/api/categories/${category.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ is_archived: !category.is_archived }),
          });
          await loadCategories();
          toast(category.is_archived ? 'Category reactivated.' : 'Category archived; history is preserved.');
        } catch (error) {
          document.getElementById('categories-feedback').textContent = error.message;
          toggle.disabled = false;
        }
      }
    });
  }

  bindAuth();
  bindShell();
  initDashboardFilters();
  initTransactionForm();
  initCsvImport();
  initTransactions();
  initCategories();
})();