import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 5 },
    { duration: '2m', target: 10 },
    { duration: '2m', target: 20 },
    { duration: '2m', target: 35 },
    { duration: '2m', target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<4000'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'https://tecman-staging.onrender.com';

function uniqueText() {
  return `Prueba k6 ${Date.now()}-${Math.floor(Math.random() * 100000)}`;
}

export default function () {
  const loginPage = http.get(`${BASE_URL}/login`);
  check(loginPage, {
    'login page ok': (r) => r.status === 200,
  });

  const loginRes = http.post(`${BASE_URL}/login`, {
    usuario: '036',
    password: 'suc036',
  }, {
    redirects: 1,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });

  check(loginRes, {
    'login ok': (r) => r.status === 200,
  });

  const nuevoPage = http.get(`${BASE_URL}/nuevo`);
  check(nuevoPage, {
    'nuevo page ok': (r) => r.status === 200,
  });

  const payload = {
    solicitante_nombre: 'Stress',
    solicitante_apellido: 'Test',
    categoria: 'Otro',
    subcategoria: 'Otro',
    descripcion: uniqueText(),
  };

  const createRes = http.post(`${BASE_URL}/nuevo`, payload, {
    redirects: 1,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });

  check(createRes, {
    'ticket create ok': (r) => r.status === 200,
    'ticket created page': (r) => r.body.includes('Ticket creado') || r.body.includes('ticket') || r.body.includes('Ticket'),
  });

  sleep(1);
}
