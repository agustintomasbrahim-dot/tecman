import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 10 },
    { duration: '2m', target: 25 },
    { duration: '2m', target: 50 },
    { duration: '2m', target: 100 },
    { duration: '2m', target: 112 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<3000'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'https://tecman-staging.onrender.com';

function extractCsrfLike(html) {
  const match = html.match(/name=["']csrf_token["']\s+value=["']([^"']+)/i);
  return match ? match[1] : null;
}

export default function () {
  const jar = http.cookieJar();

  const loginPage = http.get(`${BASE_URL}/login`);
  check(loginPage, {
    'login page 200': (r) => r.status === 200,
  });

  const payload = {
    usuario: '036',
    password: 'suc036',
  };

  const loginRes = http.post(`${BASE_URL}/login`, payload, {
    redirects: 1,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });

  check(loginRes, {
    'login sucursal ok': (r) => r.status === 200,
  });

  const panel = http.get(`${BASE_URL}/mi-panel`, { cookies: jar.cookiesForURL(BASE_URL) });
  check(panel, {
    'panel sucursal ok': (r) => r.status === 200,
  });

  const syh = http.get(`${BASE_URL}/suc/syh`, { cookies: jar.cookiesForURL(BASE_URL) });
  check(syh, {
    'syh sucursal ok': (r) => r.status === 200,
  });

  const nuevo = http.get(`${BASE_URL}/nuevo`, { cookies: jar.cookiesForURL(BASE_URL) });
  check(nuevo, {
    'nuevo ticket ok': (r) => r.status === 200,
  });

  sleep(1);
}
