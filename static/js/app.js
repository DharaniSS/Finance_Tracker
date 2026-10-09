(function () {
  'use strict';

  const STORAGE_KEY = 'spendwise-demo-v1';
  const CURRENCY = 'INR';
  const DEFAULT_THRESHOLD = 0.8;
  const palette = ['#3478c8', '#36a58a', '#e2a23a', '#d66c61', '#8667b5', '#4c9ba8', '#768493'];

  const dateOffset = (days) => {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  };

  function createSeed() {
    const categories = [
      ['Food', 420, '#e2a23a'], ['Transport', 180, '#3478c8'], ['Education', 260, '#8667b5'],
      ['Shopping', 240, '#d66c61'], ['Medical', 140, '#36a58a'], ['Travel', 350, '#4c9ba8'],
      ['Subscriptions', 75, '#768493']
    ].map(([name, budget, color], index) => ({ id: `cat-${index + 1}`, name, budget, color, archived: false }));
    const find = (name) => categories.find((category) => category.name === name).id;
    const rows = [
      [0, 'Northside Market', 48.62, 'Food', 'Weekly groceries'], [1, 'Metro Transit', 14.5, 'Transport', 'Bus pass'],
      [2, 'Campus Books', 76.9, 'Education', 'Course reader'], [3, 'Pine Street Cafe', 18.75, 'Food', 'Lunch with class'],
      [4, 'Streamline', 12.99, 'Subscriptions', 'Monthly plan'], [6, 'City Pharmacy', 23.4, 'Medical', 'Essentials'],
      [8, 'Oak & Thread', 92.3, 'Shopping', 'Everyday shoes'], [10, 'Northside Market', 36.18, 'Food', 'Groceries'],
      [12, 'Metro Transit', 14.5, 'Transport', 'Bus pass'], [15, 'Field Notes Supply', 33.6, 'Education', 'Studio materials'],
      [18, 'Pine Street Cafe', 21.25, 'Food', 'Coffee and lunch'], [22, 'Cloud Storage', 3.99, 'Subscriptions', 'Monthly plan'],
      [27, 'Northside Market', 57.42, 'Food', 'Weekly groceries'], [-34, 'Harbor Books', 42.8, 'Education', 'Reference book'],
      [-42, 'Metro Transit', 14.5, 'Transport', 'Transit card'], [-50, 'Juniper Kitchen', 67.24, 'Food', 'Groceries'],
      [-64, 'Trailbound', 184.99, 'Travel', 'Weekend rail ticket'], [-72, 'Streamline', 12.99, 'Subscriptions', 'Monthly plan'],
      [-81, 'Pine Street Cafe', 16.4, 'Food', 'Lunch'], [-94, 'Northside Market', 44.7, 'Food', 'Groceries'],
      [-102, 'Metro Transit', 14.5, 'Transport', 'Bus pass'], [-116, 'Studio Supply Co.', 112.5, 'Education', 'Project materials'],
      [-128, 'WellSpring Clinic', 48, 'Medical', 'Co-pay'], [-139, 'Northside Market', 61.3, 'Food', 'Groceries'],
      [-151, 'Pine Street Cafe', 20.1, 'Food', 'Lunch'], [-163, 'Streamline', 12.99, 'Subscriptions', 'Monthly plan'],
      [-176, 'Cedar Outfitters', 136.5, 'Shopping', 'Rain jacket'], [-189, 'Metro Transit', 14.5, 'Transport', 'Transit card'],
      [-201, 'Northside Market', 52.75, 'Food', 'Groceries'], [-214, 'Lakeview Lodge', 248, 'Travel', 'Overnight stay'],
      [-228, 'Pine Street Cafe', 17.2, 'Food', 'Lunch'], [-241, 'Campus Books', 64.95, 'Education', 'Textbook'],
      [-253, 'Northside Market', 39.2, 'Food', 'Groceries'], [-266, 'Metro Transit', 14.5, 'Transport', 'Transit card'],
      [-279, 'Streamline', 12.99, 'Subscriptions', 'Monthly plan'], [-292, 'Juniper Kitchen', 72.18, 'Food', 'Groceries'],
      [-305, 'Pine Street Cafe', 19.6, 'Food', 'Lunch'], [-319, 'City Pharmacy', 31.25, 'Medical', 'First aid supplies'],
      [-333, 'Northside Market', 48.4, 'Food', 'Groceries'], [-347, 'Metro Transit', 14.5, 'Transport', 'Bus pass'],
      [-361, 'Greenline Rail', 198, 'Travel', 'Intercity ticket'], [-374, 'Streamline', 12.99, 'Subscriptions', 'Monthly plan'],
      [-389, 'Pine Street Cafe', 15.8, 'Food', 'Lunch']
    ];
    const transactions = rows.map(([offset, merchant, amount, category, description], index) => ({
      id: `txn-seed-${index + 1}`, date: dateOffset(offset), merchant, amount,
      categoryId: find(category), description,
      anomaly: index === 6 ? { label: 'Unusual merchant', reason: 'This merchant is uncommon in the demo history.' } :
        index === 16 ? { label: 'Unusual amount', reason: 'This expense is higher than the typical amount in this category.' } : null
    }));
    return { categories, transactions, warningThreshold: DEFAULT_THRESHOLD };
  }

  const DemoStore = {
    load() {
      try {
        const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
        if (stored && Array.isArray(stored.categories) && Array.isArray(stored.transactions)) {
          stored.warningThreshold = Number(stored.warningThreshold) || DEFAULT_THRESHOLD;
          return stored;
        }
      } catch (error) {
        console.warn('SpendWise demo data could not be read; starting with sample data.', error);
      }
      const initial = createSeed();
      this.save(initial);
      return initial;
    },
    save(data) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    }
  };

  let state = DemoStore.load();
  const page = document.body.dataset.page;
  const money = (amount) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: CURRENCY, maximumFractionDigits: 2 }).format(Number(amount) || 0);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const categoryFor = (id) => state.categories.find((category) => category.id === id);
  const activeCategories = () => state.categories.filter((category) => !category.archived);
  const monthKey = (date) => String(date).slice(0, 7);
  const currentMonth = () => {
    const date = new Date();
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  };

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

  function totalsByCategory(month) {
    return state.transactions.filter((transaction) => monthKey(transaction.date) === month).reduce((totals, transaction) => {
      totals[transaction.categoryId] = (totals[transaction.categoryId] || 0) + Number(transaction.amount);
      return totals;
    }, {});
  }

  function crossings(before, after) {
    const crossed = [];
    activeCategories().forEach((category) => {
      const limit = Number(category.budget) || 0;
      if (!limit) return;
      const oldAmount = before[category.id] || 0;
      const newAmount = after[category.id] || 0;
      const threshold = limit * state.warningThreshold;
      if (oldAmount < threshold && newAmount >= threshold) crossed.push(`${category.name} reached ${Math.round(state.warningThreshold * 100)}% of its budget`);
      if (oldAmount < limit && newAmount >= limit) crossed.push(`${category.name} is over its monthly budget`);
    });
    return [...new Set(crossed)];
  }

  function reportCrossings(before, month = currentMonth()) {
    const messages = crossings(before, totalsByCategory(month));
    if (messages.length) toast(messages.join(' · '), 'warning');
  }

  function saveState() {
    DemoStore.save(state);
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
    const login = document.getElementById('login-form');
    if (login) login.addEventListener('submit', (event) => {
      event.preventDefault();
      const email = login.elements.email.value.trim();
      const password = login.elements.password.value;
      const error = document.getElementById('login-error');
      error.textContent = !email || !password ? 'Enter both your email and password.' : !login.elements.email.validity.valid ? 'Enter a valid email address.' : password.length < 6 ? 'Use at least 6 characters for this demo password.' : '';
      if (!error.textContent) window.location.href = 'dashboard.html';
    });
    const register = document.getElementById('register-form');
    if (register) register.addEventListener('submit', (event) => {
      event.preventDefault();
      const form = register.elements;
      const error = document.getElementById('register-error');
      error.textContent = !form.name.value.trim() || !form.email.value.trim() || !form.password.value || !form.confirm.value ? 'Complete every field to continue.' : !register.elements.email.validity.valid ? 'Enter a valid email address.' : form.password.value.length < 6 ? 'Use at least 6 characters for the demo password.' : form.password.value !== form.confirm.value ? 'Your passwords do not match.' : '';
      if (!error.textContent) window.location.href = 'dashboard.html';
    });
  }

  function bindShell() {
    document.querySelectorAll('[data-menu-toggle]').forEach((button) => button.addEventListener('click', () => {
      const sidebar = document.getElementById('sidebar');
      const open = sidebar.classList.toggle('sidebar-open');
      button.setAttribute('aria-expanded', String(open));
    }));
    document.querySelectorAll('[data-logout]').forEach((link) => link.addEventListener('click', () => {
      // The demo has no session to revoke; the link returns to the login screen.
    }));
  }

  function setSelectOptions(select, options, selected) {
    if (!select) return;
    select.innerHTML = options.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join('');
    if (selected !== undefined) select.value = selected;
  }

  function monthParts(value) {
    const [year, month] = value.split('-').map(Number);
    return { year, month: month - 1 };
  }

  function renderDashboard() {
    if (page !== 'dashboard') return;
    const monthFilter = document.getElementById('month-filter');
    const yearFilter = document.getElementById('year-filter');
    const selectedMonth = monthFilter.value || currentMonth();
    const [selectedYear, selectedMonthNum] = selectedMonth.split('-');
    const entries = state.transactions.filter((transaction) => monthKey(transaction.date) === selectedMonth);
    const total = entries.reduce((sum, transaction) => sum + Number(transaction.amount), 0);
    const categoryTotals = totalsByCategory(selectedMonth);
    const active = activeCategories();
    const budget = active.reduce((sum, category) => sum + Number(category.budget || 0), 0);
    const warnings = active.filter((category) => category.budget > 0 && (categoryTotals[category.id] || 0) >= category.budget * state.warningThreshold).length;
    const anomalies = entries.filter((transaction) => transaction.anomaly);
    document.getElementById('summary-spent').textContent = money(total);
    const remaining = active.reduce((sum, category) => sum + Math.max(0, Number(category.budget || 0) - (categoryTotals[category.id] || 0)), 0);
    document.getElementById('summary-remaining').textContent = money(remaining);
    document.getElementById('summary-count').textContent = entries.length;
    document.getElementById('summary-warning-count').textContent = warnings;
    document.getElementById('summary-anomaly-count').textContent = anomalies.length;
    document.getElementById('summary-attention').textContent = warnings + anomalies.length;
    document.getElementById('summary-period').textContent = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(Number(selectedYear), Number(selectedMonthNum) - 1, 1));
    renderBudgetProgress(categoryTotals);
    renderAnomalyList(anomalies.slice(0, 3), 'anomaly-preview');
    const recentBody = document.getElementById('recent-transactions');
    const recent = [...entries].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 6);
    recentBody.innerHTML = recent.map((transaction) => {
      const category = categoryFor(transaction.categoryId);
      return `<tr><td><span class="merchant-cell"><i class="category-dot" style="--category-color:${category?.color || '#768493'}"></i><strong>${escapeHtml(transaction.merchant)}</strong></span></td><td>${escapeHtml(category?.name || 'Archived')}</td><td>${formatDate(transaction.date)}</td><td class="align-right amount-cell">${money(transaction.amount)}</td></tr>`;
    }).join('');
    const empty = document.getElementById('recent-empty');
    empty.classList.toggle('hidden', recent.length > 0);
    document.querySelector('.table-panel .table-wrap').classList.toggle('hidden', recent.length === 0);
    renderCharts(selectedMonth);
    if (yearFilter.value !== selectedYear) yearFilter.value = selectedYear;
  }

  function formatDate(value) {
    const date = new Date(`${value}T12:00:00`);
    return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(date);
  }

  function renderBudgetProgress(totals) {
    const target = document.getElementById('budget-progress');
    const categories = activeCategories().filter((category) => Number(category.budget) > 0);
    target.innerHTML = categories.length ? categories.map((category) => {
      const spent = totals[category.id] || 0;
      const percent = Math.min(100, Math.round(spent / category.budget * 100));
      const status = spent >= category.budget ? 'over' : spent >= category.budget * state.warningThreshold ? 'warning' : '';
      return `<div class="budget-row"><div class="budget-row-heading"><span><i class="category-dot" style="--category-color:${category.color}"></i>${escapeHtml(category.name)}</span><span><strong>${money(spent)}</strong> <small>of ${money(category.budget)}</small></span></div><div class="progress-track" role="progressbar" aria-label="${escapeHtml(category.name)} budget used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(percent, 100)}"><span class="progress-fill ${status}" style="width:${percent}%;--category-color:${category.color}"></span></div><small class="budget-footnote">${Math.round(spent / category.budget * 100)}% used${spent > category.budget ? ` · ${money(spent - category.budget)} over` : ''}</small></div>`;
    }).join('') : '<div class="empty-inline">No active budgets yet. Add a category budget to track progress.</div>';
  }

  function renderAnomalyList(transactions, targetId) {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.innerHTML = transactions.length ? transactions.map((transaction) => {
      const category = categoryFor(transaction.categoryId);
      return `<div class="alert-item"><span class="alert-mark">!</span><div class="alert-copy"><strong>${escapeHtml(transaction.anomaly.label)}</strong><span>${escapeHtml(transaction.merchant)} · ${escapeHtml(category?.name || 'Archived')} · ${money(transaction.amount)}</span><small>${escapeHtml(transaction.anomaly.reason)}</small></div></div>`;
    }).join('') : '<div class="empty-inline">No unusual activity in this month.</div>';
  }

  function renderCharts(month) {
    if (typeof Plotly === 'undefined') return;
    const entries = state.transactions.filter((transaction) => monthKey(transaction.date) === month);
    const { year, month: monthIndex } = monthParts(month);
    const days = new Date(year, monthIndex + 1, 0).getDate();
    const daily = Array(days).fill(0);
    entries.forEach((transaction) => { daily[Number(transaction.date.slice(8, 10)) - 1] += Number(transaction.amount); });
    const common = { paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: { family: 'DM Sans, sans-serif', color: '#c3cbd1', size: 11 }, margin: { l: 48, r: 14, t: 8, b: 32 }, xaxis: { gridcolor: 'rgba(255,255,255,.09)', zeroline: false, linecolor: 'rgba(255,255,255,.12)' }, yaxis: { gridcolor: 'rgba(255,255,255,.09)', zeroline: false, tickprefix: '₹', linecolor: 'transparent' }, showlegend: false };
    Plotly.react('trend-chart', [{ x: daily.map((_, index) => index + 1), y: daily, type: 'scatter', mode: 'lines+markers', line: { color: '#f2b84b', width: 3, shape: 'spline' }, marker: { color: '#ffd77e', size: 5 }, fill: 'tozeroy', fillcolor: 'rgba(242,184,75,.13)', hovertemplate: 'Day %{x}<br>₹%{y:.2f}<extra></extra>' }], { ...common, xaxis: { ...common.xaxis, title: 'Day of month', dtick: Math.max(1, Math.ceil(days / 8)) }, yaxis: { ...common.yaxis, rangemode: 'tozero' } }, { responsive: true, displayModeBar: false });
    const byCategory = state.categories.map((category) => ({ category, amount: entries.filter((transaction) => transaction.categoryId === category.id).reduce((sum, transaction) => sum + Number(transaction.amount), 0) })).filter((item) => item.amount > 0);
    Plotly.react('category-chart', byCategory.length ? [{ labels: byCategory.map((item) => item.category.name), values: byCategory.map((item) => item.amount), type: 'pie', hole: 0.68, marker: { colors: byCategory.map((item) => item.category.color), line: { color: '#26313b', width: 3 } }, textinfo: 'none', hovertemplate: '%{label}<br>₹%{value:.2f} (%{percent})<extra></extra>' }] : [], { ...common, margin: { l: 8, r: 8, t: 4, b: 4 }, showlegend: byCategory.length > 0, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: '#c3cbd1' } }, annotations: byCategory.length ? [] : [{ text: 'No spending yet', showarrow: false, font: { color: '#b6c0c8', size: 13 } }] }, { responsive: true, displayModeBar: false });
    const months = Array.from({ length: 6 }, (_, index) => {
      const date = new Date(year, monthIndex - 5 + index, 1);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    });
    const monthlyTotals = months.map((key) => state.transactions.filter((transaction) => monthKey(transaction.date) === key).reduce((sum, transaction) => sum + Number(transaction.amount), 0));
    Plotly.react('monthly-chart', [{ x: months.map((key) => new Intl.DateTimeFormat('en-US', { month: 'short' }).format(new Date(`${key}-01T12:00:00`))), y: monthlyTotals, type: 'bar', marker: { color: months.map((key) => key === month ? '#f2b84b' : 'rgba(212,225,235,.3)'), line: { color: months.map((key) => key === month ? '#f7ca70' : 'rgba(212,225,235,.24)'), width: 1 }, cornerradius: 4 }, hovertemplate: '%{x}<br>₹%{y:.2f}<extra></extra>' }], { ...common, bargap: 0.42, yaxis: { ...common.yaxis, rangemode: 'tozero' } }, { responsive: true, displayModeBar: false });
  }

  function initDashboardFilters() {
    if (page !== 'dashboard') return;
    const month = document.getElementById('month-filter');
    const year = document.getElementById('year-filter');
    const allMonths = new Set(state.transactions.map((transaction) => monthKey(transaction.date)));
    allMonths.add(currentMonth());
    const months = [...allMonths].sort().reverse();
    setSelectOptions(month, months.map((value) => ({ value, label: new Intl.DateTimeFormat('en-US', { month: 'long' }).format(new Date(`${value}-01T12:00:00`)) })), months.includes(currentMonth()) ? currentMonth() : months[0]);
    const years = [...new Set(months.map((value) => value.slice(0, 4)))].sort().reverse();
    setSelectOptions(year, years.map((value) => ({ value, label: value })), month.value.slice(0, 4));
    const applyYear = () => {
      const options = [...month.options].filter((option) => option.value.startsWith(year.value));
      if (!options.some((option) => option.value === month.value)) month.value = options[0]?.value || currentMonth();
      renderDashboard();
    };
    month.addEventListener('change', () => { year.value = month.value.slice(0, 4); renderDashboard(); });
    year.addEventListener('change', applyYear);
    renderDashboard();
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
    updateCategoryOptions();
    const params = new URLSearchParams(window.location.search);
    if (params.has('edit')) {
      const transaction = state.transactions.find((item) => item.id === params.get('edit'));
      if (transaction) populateTransactionForm(transaction);
    }
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const id = document.getElementById('transaction-id').value;
      const merchant = document.getElementById('entry-merchant').value.trim();
      const amount = Number(document.getElementById('entry-amount').value);
      const categoryId = document.getElementById('entry-category').value;
      const date = dateInput.value;
      const error = document.getElementById('transaction-error');
      if (!date || !merchant || !categoryId || !Number.isFinite(amount) || amount <= 0) {
        error.textContent = 'Enter a valid date, merchant, positive amount, and category.';
        return;
      }
      const transactionMonth = monthKey(date);
      const before = totalsByCategory(transactionMonth);
      const existing = state.transactions.find((item) => item.id === id);
      const transaction = { id: id || `txn-${Date.now()}`, date, merchant, amount: Math.round(amount * 100) / 100, categoryId, description: document.getElementById('entry-description').value.trim(), anomaly: existing?.anomaly || null };
      if (existing) state.transactions = state.transactions.map((item) => item.id === id ? transaction : item);
      else state.transactions.push(transaction);
      saveState();
      renderDashboard();
      error.textContent = '';
      form.reset();
      dateInput.value = dateOffset(0);
      document.getElementById('transaction-id').value = '';
      setEntryMode(false);
      toast(existing ? 'Transaction updated.' : 'Transaction added.');
      reportCrossings(before, transactionMonth);
    });
    document.getElementById('cancel-edit').addEventListener('click', () => { form.reset(); dateInput.value = dateOffset(0); setEntryMode(false); });
  }

  function populateTransactionForm(transaction) {
    updateCategoryOptions();
    document.getElementById('transaction-id').value = transaction.id;
    document.getElementById('entry-date').value = transaction.date;
    document.getElementById('entry-merchant').value = transaction.merchant;
    document.getElementById('entry-amount').value = transaction.amount;
    document.getElementById('entry-category').value = transaction.categoryId;
    document.getElementById('entry-description').value = transaction.description || '';
    setEntryMode(true);
    document.getElementById('manual-entry').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function setEntryMode(editing) {
    document.getElementById('entry-heading').textContent = editing ? 'Edit transaction' : 'Add a transaction';
    document.getElementById('save-transaction').textContent = editing ? 'Save changes' : 'Save transaction';
    document.getElementById('cancel-edit').classList.toggle('hidden', !editing);
  }

  function parseCsvLine(line) {
    const values = [];
    let value = '';
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const char = line[index];
      if (char === '"' && quoted && line[index + 1] === '"') { value += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === ',' && !quoted) { values.push(value.trim()); value = ''; }
      else value += char;
    }
    values.push(value.trim());
    return values;
  }

  function parseCsv(text) {
    const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter((line) => line.trim());
    if (lines.length < 2) throw new Error('The CSV needs a header row and at least one transaction row.');
    const headers = parseCsvLine(lines[0]).map((header) => header.toLowerCase().replace(/[^a-z]/g, ''));
    const column = (names) => headers.findIndex((header) => names.includes(header));
    const indexes = { date: column(['date', 'transactiondate']), merchant: column(['merchant', 'name', 'payee']), amount: column(['amount', 'total', 'value']), category: column(['category', 'type']), description: column(['description', 'note', 'memo', 'details']) };
    const missing = ['date', 'merchant', 'amount', 'category'].filter((key) => indexes[key] < 0);
    if (missing.length) throw new Error(`Missing required column${missing.length > 1 ? 's' : ''}: ${missing.join(', ')}.`);
    const seen = new Set(state.transactions.map((transaction) => `${transaction.date}|${transaction.merchant.toLowerCase()}|${Number(transaction.amount)}`));
    return lines.slice(1).map((line, index) => {
      const fields = parseCsvLine(line);
      const rawDate = fields[indexes.date] || '';
      const date = normalizeDate(rawDate);
      const merchant = (fields[indexes.merchant] || '').trim();
      const amountText = (fields[indexes.amount] || '').replace(/[$,\s]/g, '');
      const amount = Number(amountText);
      const categoryName = (fields[indexes.category] || '').trim();
      const category = state.categories.find((item) => item.name.toLowerCase() === categoryName.toLowerCase() && !item.archived);
      const problems = [];
      if (!date) problems.push('Invalid date');
      if (!merchant) problems.push('Merchant is required');
      if (!Number.isFinite(amount) || amount <= 0) problems.push('Amount must be a positive number');
      if (!categoryName) problems.push('Category is required');
      else if (!category) problems.push(`Unknown active category: ${categoryName}`);
      const duplicateKey = `${date}|${merchant.toLowerCase()}|${amount}`;
      const duplicate = Boolean(date && merchant && Number.isFinite(amount) && seen.has(duplicateKey));
      if (date && merchant && Number.isFinite(amount)) seen.add(duplicateKey);
      return { row: index + 2, date, merchant, amount, categoryId: category?.id || '', categoryName, description: indexes.description >= 0 ? fields[indexes.description] || '' : '', problems, duplicate, valid: problems.length === 0 && !duplicate };
    });
  }

  function normalizeDate(value) {
    const trimmed = value.trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
      const date = new Date(`${trimmed}T00:00:00Z`);
      return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === trimmed ? trimmed : '';
    }
    const match = trimmed.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/);
    if (!match) return '';
    const candidate = `${match[3]}-${match[1].padStart(2, '0')}-${match[2].padStart(2, '0')}`;
    const date = new Date(`${candidate}T00:00:00Z`);
    return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === candidate ? candidate : '';
  }

  function initCsvImport() {
    const input = document.getElementById('csv-file');
    if (!input) return;
    const zone = document.getElementById('csv-dropzone');
    let preview = [];
    const loadFile = async (file) => {
      if (!file || !file.name.toLowerCase().endsWith('.csv')) { toast('Choose a CSV file to continue.', 'error'); return; }
      try {
        preview = parseCsv(await file.text());
        renderCsvPreview(preview);
        document.getElementById('csv-feedback').textContent = `${file.name} ready for review.`;
      } catch (error) {
        document.getElementById('csv-preview-wrap').classList.add('hidden');
        document.getElementById('csv-feedback').textContent = error.message;
      }
    };
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
    input.addEventListener('change', () => loadFile(input.files[0]));
    ['dragenter', 'dragover'].forEach((name) => zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add('dropzone-active'); }));
    ['dragleave', 'drop'].forEach((name) => zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.remove('dropzone-active'); }));
    zone.addEventListener('drop', (event) => loadFile(event.dataTransfer.files[0]));
    document.getElementById('import-valid-rows').addEventListener('click', () => {
      const validRows = preview.filter((row) => row.valid);
      if (!validRows.length) { toast('There are no valid, non-duplicate rows to import.', 'warning'); return; }
      const beforeByMonth = new Map();
      validRows.forEach((row) => { const key = monthKey(row.date); if (!beforeByMonth.has(key)) beforeByMonth.set(key, totalsByCategory(key)); });
      state.transactions.push(...validRows.map((row) => ({ id: `txn-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, date: row.date, merchant: row.merchant, amount: Math.round(row.amount * 100) / 100, categoryId: row.categoryId, description: row.description, anomaly: null })));
      saveState();
      renderDashboard();
      document.getElementById('csv-feedback').textContent = `${validRows.length} transaction${validRows.length === 1 ? '' : 's'} imported.`;
      toast(`${validRows.length} transaction${validRows.length === 1 ? '' : 's'} imported.`);
      beforeByMonth.forEach((before, month) => reportCrossings(before, month));
      preview = [];
      document.getElementById('csv-preview-wrap').classList.add('hidden');
      input.value = '';
    });
  }

  function renderCsvPreview(rows) {
    const wrap = document.getElementById('csv-preview-wrap');
    wrap.classList.remove('hidden');
    const valid = rows.filter((row) => row.valid).length;
    const duplicates = rows.filter((row) => row.duplicate).length;
    document.getElementById('csv-preview-summary').textContent = `${valid} ready · ${rows.length - valid - duplicates} with errors · ${duplicates} duplicate${duplicates === 1 ? '' : 's'}`;
    document.getElementById('csv-errors').innerHTML = rows.filter((row) => row.problems.length || row.duplicate).map((row) => `<div class="validation-message ${row.duplicate && !row.problems.length ? 'validation-warning' : ''}"><strong>Row ${row.row}:</strong> ${escapeHtml([...row.problems, ...(row.duplicate ? ['Possible duplicate transaction'] : [])].join(' · '))}</div>`).join('');
    document.getElementById('csv-preview-body').innerHTML = rows.map((row) => `<tr><td>${row.row}</td><td>${escapeHtml(row.date || '—')}</td><td>${escapeHtml(row.merchant || '—')}</td><td>${escapeHtml(row.categoryName || '—')}</td><td class="align-right">${Number.isFinite(row.amount) ? money(row.amount) : '—'}</td><td><span class="status-pill ${row.valid ? 'status-ready' : row.duplicate && !row.problems.length ? 'status-duplicate' : 'status-invalid'}">${row.valid ? 'Ready' : row.duplicate && !row.problems.length ? 'Duplicate' : 'Review'}</span></td></tr>`).join('');
    document.getElementById('import-valid-rows').disabled = valid === 0;
  }

  function initTransactions() {
    const body = document.getElementById('transactions-body');
    if (!body) return;
    const search = document.getElementById('transaction-search');
    const categoryFilter = document.getElementById('transaction-category-filter');
    const monthFilter = document.getElementById('transaction-month-filter');
    setSelectOptions(categoryFilter, [{ value: '', label: 'All categories' }, ...state.categories.map((category) => ({ value: category.id, label: `${category.name}${category.archived ? ' (archived)' : ''}` }))]);
    const render = () => {
      const query = search.value.trim().toLowerCase();
      const selectedCategory = categoryFilter.value;
      const selectedMonth = monthFilter.value;
      const filtered = [...state.transactions].sort((a, b) => b.date.localeCompare(a.date)).filter((transaction) => {
        const textMatch = `${transaction.merchant} ${transaction.description || ''}`.toLowerCase().includes(query);
        return textMatch && (!selectedCategory || transaction.categoryId === selectedCategory) && (!selectedMonth || monthKey(transaction.date) === selectedMonth);
      });
      body.innerHTML = filtered.map((transaction) => {
        const category = categoryFor(transaction.categoryId);
        return `<tr><td><span class="merchant-cell"><i class="category-dot" style="--category-color:${category?.color || '#768493'}"></i><strong>${escapeHtml(transaction.merchant)}</strong></span></td><td>${escapeHtml(category?.name || 'Archived')}</td><td>${formatDate(transaction.date)}, ${transaction.date.slice(0, 4)}</td><td class="description-cell">${escapeHtml(transaction.description || '—')}</td><td class="align-right amount-cell">${money(transaction.amount)}</td><td class="action-cell"><a class="icon-button table-action" href="expenses.html?edit=${encodeURIComponent(transaction.id)}#manual-entry" aria-label="Edit ${escapeHtml(transaction.merchant)}">✎</a><button class="icon-button table-action delete-transaction" type="button" data-delete-transaction="${escapeHtml(transaction.id)}" aria-label="Delete ${escapeHtml(transaction.merchant)}">×</button></td></tr>`;
      }).join('');
      document.getElementById('transactions-empty').classList.toggle('hidden', filtered.length > 0);
      document.querySelector('.table-panel .table-wrap').classList.toggle('hidden', filtered.length === 0);
    };
    [search, categoryFilter, monthFilter].forEach((control) => control.addEventListener('input', render));
    body.addEventListener('click', (event) => {
      const button = event.target.closest('[data-delete-transaction]');
      if (!button) return;
      const transaction = state.transactions.find((item) => item.id === button.dataset.deleteTransaction);
      if (!transaction || !window.confirm(`Delete the ${transaction.merchant} transaction?`)) return;
      state.transactions = state.transactions.filter((item) => item.id !== transaction.id);
      saveState();
      render();
      toast('Transaction deleted. Budget totals have been recalculated.');
    });
    render();
  }

  let categoryView = 'active';
  function renderCategories() {
    const target = document.getElementById('category-list');
    if (!target) return;
    const items = state.categories.filter((category) => category.archived === (categoryView === 'archived'));
    document.getElementById('category-count').textContent = `${items.length} ${categoryView} categor${items.length === 1 ? 'y' : 'ies'}`;
    const totals = totalsByCategory(currentMonth());
    target.innerHTML = items.length ? items.map((category) => {
      const spent = totals[category.id] || 0;
      const percentage = category.budget > 0 ? Math.round(spent / category.budget * 100) : 0;
      return `<article class="category-card"><div class="category-card-top"><span class="category-identity"><i class="category-swatch" style="--category-color:${category.color}"></i><strong>${escapeHtml(category.name)}</strong></span><div class="category-actions"><button class="icon-button table-action" type="button" data-edit-category="${escapeHtml(category.id)}" aria-label="Edit ${escapeHtml(category.name)}">✎</button><button class="button button-quiet button-small" type="button" data-toggle-category="${escapeHtml(category.id)}">${category.archived ? 'Reactivate' : 'Archive'}</button></div></div><div class="category-budget-line"><span>Monthly limit</span><strong>${money(category.budget)}</strong></div><div class="progress-track" role="progressbar" aria-label="${escapeHtml(category.name)} budget used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(percentage, 100)}"><span class="progress-fill ${percentage >= 100 ? 'over' : percentage >= state.warningThreshold * 100 ? 'warning' : ''}" style="width:${Math.min(percentage, 100)}%;--category-color:${category.color}"></span></div><small class="category-spend-caption">${money(spent)} spent this month${category.archived ? ' · archived' : ` · ${percentage}% used`}</small></article>`;
    }).join('') : `<div class="empty-state"><span class="empty-symbol">◷</span><strong>No ${categoryView} categories</strong><span>${categoryView === 'active' ? 'Create a category to start setting budget limits.' : 'Archived categories appear here and keep their transaction history.'}</span></div>`;
  }

  function initCategories() {
    const form = document.getElementById('category-form');
    if (!form) return;
    renderCategories();
    document.querySelectorAll('[data-category-view]').forEach((button) => button.addEventListener('click', () => {
      categoryView = button.dataset.categoryView;
      document.querySelectorAll('[data-category-view]').forEach((item) => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); });
      renderCategories();
    }));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const id = document.getElementById('category-id').value;
      const name = document.getElementById('category-name').value.trim();
      const budget = Number(document.getElementById('category-budget').value);
      const error = document.getElementById('category-error');
      const duplicate = state.categories.some((category) => category.name.toLowerCase() === name.toLowerCase() && category.id !== id);
      if (!name || !Number.isFinite(budget) || budget <= 0) error.textContent = 'Enter a category name and a monthly budget greater than zero.';
      else if (duplicate) error.textContent = 'A category with this name already exists.';
      else {
        if (id) state.categories = state.categories.map((category) => category.id === id ? { ...category, name, budget, color: document.getElementById('category-color').value } : category);
        else state.categories.push({ id: `cat-${Date.now()}`, name, budget, color: document.getElementById('category-color').value, archived: false });
        saveState();
        form.reset();
        document.getElementById('category-id').value = '';
        document.getElementById('category-form-title').textContent = 'Create a category';
        document.getElementById('save-category').textContent = 'Add category';
        document.getElementById('cancel-category-edit').classList.add('hidden');
        error.textContent = '';
        renderCategories();
        updateCategoryOptions();
        renderDashboard();
        toast(id ? 'Category updated.' : 'Category created.');
      }
    });
    document.getElementById('cancel-category-edit').addEventListener('click', () => {
      form.reset(); document.getElementById('category-id').value = ''; document.getElementById('category-form-title').textContent = 'Create a category'; document.getElementById('save-category').textContent = 'Add category'; document.getElementById('cancel-category-edit').classList.add('hidden'); document.getElementById('category-error').textContent = '';
    });
    document.getElementById('warning-threshold').value = Math.round(state.warningThreshold * 100);
    document.getElementById('threshold-value').value = `${Math.round(state.warningThreshold * 100)}%`;
    document.getElementById('warning-threshold').addEventListener('input', (event) => {
      state.warningThreshold = Number(event.target.value) / 100;
      document.getElementById('threshold-value').value = `${event.target.value}%`;
      saveState(); renderCategories(); renderDashboard();
    });
    document.getElementById('category-list').addEventListener('click', (event) => {
      const edit = event.target.closest('[data-edit-category]');
      const toggle = event.target.closest('[data-toggle-category]');
      if (edit) {
        const category = state.categories.find((item) => item.id === edit.dataset.editCategory);
        if (!category) return;
        document.getElementById('category-id').value = category.id;
        document.getElementById('category-name').value = category.name;
        document.getElementById('category-budget').value = category.budget;
        document.getElementById('category-color').value = category.color;
        document.getElementById('category-form-title').textContent = 'Edit category';
        document.getElementById('save-category').textContent = 'Save changes';
        document.getElementById('cancel-category-edit').classList.remove('hidden');
        document.getElementById('category-name').focus();
      }
      if (toggle) {
        const category = state.categories.find((item) => item.id === toggle.dataset.toggleCategory);
        if (!category) return;
        category.archived = !category.archived;
        saveState(); renderCategories(); updateCategoryOptions(); renderDashboard();
        toast(category.archived ? `${category.name} archived. Past transactions are preserved.` : `${category.name} reactivated.`);
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