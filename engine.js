// Motor de cálculo — Replantea
// Fechas como 'YYYY-MM-DD'. Montos en COP.
const Engine = (() => {
  const parse = s => { const [y, m, d] = s.split('-').map(Number); return { y, m, d }; };
  const isLastFeb = ({ y, m, d }) => m === 2 && d === new Date(Date.UTC(y, 2, 0)).getUTCDate();
  // DAYS360 método US (NASD), igual a Excel DAYS360(a,b) por defecto
  function days360(a, b) {
    const A = parse(a), B = parse(b);
    let d1 = A.d, d2 = B.d;
    if (isLastFeb(A) && isLastFeb(B)) d2 = 30;
    if (isLastFeb(A)) d1 = 30;
    if (d2 === 31 && d1 >= 30) d2 = 30;
    if (d1 === 31) d1 = 30;
    return (B.y - A.y) * 360 + (B.m - A.m) * 30 + (d2 - d1);
  }
  const daysActual = (a, b) => (Date.parse(b) - Date.parse(a)) / 86400000;

  // Línea de tiempo: D = plan pactado (compañía), F = pagos comprador (recaudo + propuesta)
  function timeline(pactado, pagos) {
    const map = new Map();
    for (const p of pactado) { const r = map.get(p.fecha) || { fecha: p.fecha, D: 0, F: 0 }; r.D += p.valor; map.set(p.fecha, r); }
    for (const p of pagos) { const r = map.get(p.fecha) || { fecha: p.fecha, D: 0, F: 0 }; r.F += p.valor; map.set(p.fecha, r); }
    return [...map.values()].sort((a, b) => a.fecha.localeCompare(b.fecha));
  }

  // Réplica exacta de la plantilla Excel (columnas H, I, J)
  // tasaCia: interés mensual reconocido al comprador cuando va adelantado (saldo < 0)
  // tasaCliente: interés mensual cobrado cuando va atrasado (saldo >= 0)
  function liquidacion(pactado, pagos, tasaCia, tasaCliente) {
    const rows = timeline(pactado, pagos);
    let I = 0, J = 0, totalH = 0;
    const out = [];
    rows.forEach((r, k) => {
      let H = 0;
      if (k === 0) {
        I = (0 < r.F) ? 0 : -r.F; // =IF((I0+H)<F,0,I0+H-F)
        if (I < 0) I = 0;
        J = r.D - r.F;
      } else {
        const prev = rows[k - 1];
        const rate = J >= 0 ? tasaCliente : tasaCia;
        H = rate * (12 * days360(prev.fecha, r.fecha) / 360) * J;
        const IH = I + H;
        let nI, nJ;
        if (IH < 0) {
          nI = (IH + r.D) >= 0 ? 0 : IH + r.D;
          nJ = (IH + r.D) >= 0 ? J + (IH + r.D) - r.F : J - r.F;
        } else {
          nI = IH < r.F ? 0 : IH - r.F;
          nJ = J + r.D - (IH < r.F ? r.F - IH : 0);
        }
        I = nI; J = nJ;
      }
      totalH += H;
      out.push({ ...r, H, I, J });
    });
    return { ajuste: totalH, filas: out };
  }

  // VPN: descuenta ambos flujos a la fecha inicial con tasa mensual compuesta (días reales / 30.4167)
  // y expresa la diferencia a la fecha del último pago (fecha de liquidación del ajuste).
  function vpn(pactado, pagos, tasa) {
    const all = [...pactado, ...pagos].map(p => p.fecha).sort();
    const t0 = all[0], tN = all[all.length - 1];
    const m = f => daysActual(t0, f) / (365 / 12);
    const pv = fl => fl.reduce((s, p) => s + p.valor / Math.pow(1 + tasa, m(p.fecha)), 0);
    const diff = pv(pactado) - pv(pagos); // >0: el comprador entrega menos valor presente → sobrecargo
    return { ajuste: diff * Math.pow(1 + tasa, m(tN)), pvPactado: pv(pactado), pvPagos: pv(pagos), fechaLiquidacion: tN };
  }

  // Evalúa una propuesta con la configuración del proyecto y aplica tope/umbral
  function evaluar({ pactado, recaudo, propuesta, cfg, valorVenta }) {
    const pagos = [...recaudo, ...propuesta];
    let ajuste;
    if (cfg.metodo === 'liquidacion') ajuste = liquidacion(pactado, pagos, cfg.tasaCia, cfg.tasaCliente).ajuste;
    else ajuste = vpn(pactado, pagos, cfg.tasaVpn).ajuste;
    ajuste = Math.round(ajuste);
    const tope = Math.round(valorVenta * cfg.topePct);
    const topado = ajuste < 0 && -ajuste > tope;
    const aplicado = topado ? -tope : ajuste;
    const requiereAprobacion = aplicado < 0 && -aplicado > valorVenta * cfg.umbralPct;
    return { ajusteCalculado: ajuste, ajuste: aplicado, topado, tope, requiereAprobacion };
  }

  return { days360, liquidacion, vpn, evaluar, timeline };
})();
if (typeof module !== 'undefined') module.exports = Engine;
