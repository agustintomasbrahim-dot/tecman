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
    http_req_duration: ['p(95)<2500'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'https://tecman.onrender.com';

export default function () {
  const home = http.get(`${BASE_URL}/`);
  check(home, {
    'home 200': (r) => r.status === 200,
  });

  const sucLogin = http.get(`${BASE_URL}/login`);
  check(sucLogin, {
    'suc login visible': (r) => r.status === 200,
  });

  const syhLogin = http.get(`${BASE_URL}/syh/login`);
  check(syhLogin, {
    'syh login visible': (r) => r.status === 200,
  });

  const adminLogin = http.get(`${BASE_URL}/admin/login`);
  check(adminLogin, {
    'admin login visible': (r) => r.status === 200,
  });

  sleep(1);
}
