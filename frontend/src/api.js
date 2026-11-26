// Offline-first API client with Outbox & Automatic Sync
const API_BASE = '/api';

export const api = {
  // Offline outbox management in localStorage
  getOutbox: () => {
    try {
      return JSON.parse(localStorage.getItem('wexora_outbox') || '[]');
    } catch {
      return [];
    }
  },

  saveOutbox: (items) => {
    localStorage.setItem('wexora_outbox', JSON.stringify(items));
  },

  addToOutbox: (orderPayload) => {
    const outbox = api.getOutbox();
    const item = {
      client_uuid: 'UUID-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9),
      device_created_at: new Date().toISOString(),
      payload: orderPayload,
      status: 'PENDING_SYNC',
      retries: 0
    };
    outbox.push(item);
    api.saveOutbox(outbox);
    return item;
  },

  syncOutbox: async () => {
    const outbox = api.getOutbox();
    if (!outbox.length) return { synced: 0, pending: 0 };

    const remaining = [];
    let synced = 0;

    for (const item of outbox) {
      try {
        const res = await fetch(`${API_BASE}/orders`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...item.payload,
            client_uuid: item.client_uuid,
            device_created_at: item.device_created_at
          })
        });
        if (res.ok) {
          synced++;
        } else {
          item.retries += 1;
          remaining.push(item);
        }
      } catch (err) {
        item.retries += 1;
        remaining.push(item);
      }
    }

    api.saveOutbox(remaining);
    return { synced, pending: remaining.length };
  },

  // Standard fetch wrapper
  request: async (path, options = {}) => {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      ...options
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'API request failed');
    }
    return res.json();
  },

  // API endpoints
  getDashboard: () => api.request('/dashboard/owner'),
  getMasters: () => api.request('/masters'),
  getUsers: () => api.request('/users'),
  
  // Orders
  getOrders: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return api.request(`/orders${q ? '?' + q : ''}`);
  },
  getOrder: (id) => api.request(`/orders/${id}`),
  createOrder: async (data, isOnline = true) => {
    if (!isOnline) {
      return api.addToOutbox(data);
    }
    try {
      const client_uuid = 'UUID-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
      return await api.request('/orders', {
        method: 'POST',
        body: JSON.stringify({ ...data, client_uuid })
      });
    } catch (e) {
      // If network fails, queue to outbox
      console.warn("Network failed, saving order to offline outbox:", e);
      return api.addToOutbox(data);
    }
  },
  approveOrder: (id, approvals, admin_id) => api.request(`/orders/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approvals, admin_id })
  }),
  invoiceOrder: (id, admin_id) => api.request(`/orders/${id}/invoice`, {
    method: 'POST',
    body: JSON.stringify({ admin_id })
  }),
  dispatchOrder: (id, data) => api.request(`/orders/${id}/dispatch`, {
    method: 'POST',
    body: JSON.stringify(data)
  }),

  // Invoices & Payments
  getInvoices: () => api.request('/invoices'),
  getInvoice: (id) => api.request(`/invoices/${id}`),
  getOutstanding: (customerId) => api.request(`/customers/${customerId}/outstanding`),
  recordPayment: (data) => api.request('/payments', {
    method: 'POST',
    body: JSON.stringify(data)
  }),

  // Purchases
  getPurchases: () => api.request('/purchases'),
  createPurchase: (data) => api.request('/purchases', {
    method: 'POST',
    body: JSON.stringify(data)
  }),

  // Production
  getProductionRuns: () => api.request('/production-runs'),
  createProductionRun: (data) => api.request('/production-runs', {
    method: 'POST',
    body: JSON.stringify(data)
  }),

  // Inventory & Provenance
  getInventorySummary: () => api.request('/inventory/summary'),
  getInventoryLedger: (itemId) => api.request(`/inventory/ledger${itemId ? '?item_id=' + itemId : ''}`),

  // Reports & Audit
  getSalesReport: (from, to) => api.request(`/reports/sales${from ? `?from_date=${from}&to_date=${to}` : ''}`),
  getGstReport: (from, to) => api.request(`/reports/gst${from ? `?from_date=${from}&to_date=${to}` : ''}`),
  getAuditVerify: () => api.request('/audit/verify'),

  // Benchmark
  resetBenchmark: () => api.request('/benchmark/reset', { method: 'POST' }),
  runFullBenchmark: () => api.request('/benchmark/run-full', { method: 'POST' }),
};
