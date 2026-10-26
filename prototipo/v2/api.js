/* api.js — cliente de la API de Replantea (sesión + CSRF) y cabecera común.
   Las páginas se sirven desde el mismo dominio que la API, así que la cookie de sesión
   viaja sola. Las peticiones que modifican datos llevan el token CSRF en X-CSRFToken. */
const API = (() => {
  const cookie = nombre => (document.cookie.split('; ').find(c => c.startsWith(nombre + '=')) || '').split('=')[1];

  async function pedir(metodo, url, cuerpo) {
    const cab = { 'Accept': 'application/json' };
    let body;
    if (cuerpo !== undefined) { cab['Content-Type'] = 'application/json'; body = JSON.stringify(cuerpo); }
    if (metodo !== 'GET') {
      let t = cookie('csrftoken');
      if (!t) { await fetch('/api/auth/csrf', { credentials: 'same-origin' }); t = cookie('csrftoken'); }
      if (t) cab['X-CSRFToken'] = t;
    }
    let r;
    try { r = await fetch('/api' + url, { method: metodo, headers: cab, body, credentials: 'same-origin' }); }
    catch (e) { const err = new Error('No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.'); err.status = 0; throw err; }
    let datos = null;
    try { datos = await r.json(); } catch (e) { /* respuesta sin cuerpo */ }
    if (!r.ok) {
      const d = datos && datos.detail;
      const err = new Error(typeof d === 'string' ? d : (r.status === 422 ? 'Hay datos inválidos en la solicitud.' : `Error ${r.status}`));
      err.status = r.status;
      err.errores = (datos && datos.errores) || [];
      throw err;
    }
    return datos;
  }
  return {
    get: u => pedir('GET', u),
    post: (u, b) => pedir('POST', u, b === undefined ? {} : b),
    patch: (u, b) => pedir('PATCH', u, b),
    delete: u => pedir('DELETE', u),
  };
})();

const ROLES = { administrador: 'Administrador', gerente: 'Gerente', asesor: 'Asesor' };
const NAV = [
  { href: '/app/asesor.html', t: 'Solicitudes', roles: ['asesor', 'gerente', 'administrador'] },
  { href: '/app/aprobaciones.html', t: 'Aprobaciones', roles: ['gerente', 'administrador'] },
  { href: '/app/proyectos.html', t: 'Proyectos', roles: ['gerente', 'administrador'] },
];
const inicioDe = u => (u.rol === 'gerente' ? '/app/aprobaciones.html' : '/app/asesor.html');

/** Exige sesión (y, si se indican, uno de los roles). Si no, lleva al login. Devuelve el usuario o null. */
async function exigirSesion(roles) {
  try {
    const u = await API.get('/auth/yo');
    if (roles && u.rol !== 'administrador' && !roles.includes(u.rol)) { location.replace(inicioDe(u)); return null; }
    return u;
  } catch (e) {
    if (e.status === 401) { location.replace('/app/login.html?next=' + encodeURIComponent(location.pathname + location.hash)); return null; }
    throw e;
  }
}

/** Dibuja logo, navegación según el rol, usuario y "Salir" dentro de #cab. */
function pintarCabecera(u, actual) {
  const links = NAV.filter(n => n.roles.includes(u.rol)).map(n => `<a href="${n.href}" ${n.href === actual ? 'aria-current="page"' : ''}>${n.t}</a>`).join('');
  document.getElementById('cab').innerHTML = `
    <a href="${inicioDe(u)}"><img class="logo" src="/app/img/logo-vyp.svg" alt="Viviendas y Proyectos, bien hechos"></a>
    <nav class="nav" aria-label="Principal">${links}</nav>
    <span class="user">${u.nombre.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))} · ${ROLES[u.rol] || u.rol}
      <button class="txt-btn" id="btn-salir" type="button">Salir</button></span>`;
  document.getElementById('btn-salir').onclick = async () => {
    try { await API.post('/auth/logout'); } catch (e) { /* si la sesión ya expiró, igual salimos */ }
    location.href = '/app/login.html';
  };
}
