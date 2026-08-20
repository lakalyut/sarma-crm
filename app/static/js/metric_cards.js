function formatMetricNumber(value, digits = 2) {
    return Number(value || 0).toLocaleString("ru-RU", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
    });
}

function metricCalcDelta(current, base) {
    current = Number(current || 0);
    base = Number(base || 0);

    if (!base) return null;

    return ((current - base) / base) * 100;
}

function metricCalcAverage(arr) {
    const values = (arr || []).map(Number).filter(v => !Number.isNaN(v));

    if (!values.length) return null;

    const sum = values.reduce((acc, value) => acc + value, 0);
    return sum / values.length;
}

function metricFormatDelta(delta, label, diff, digits = 2, unit = "") {
    if (delta === null || delta === undefined || Number.isNaN(delta)) {
        return `
            <div class="metric-delta-row">
                <span class="metric-delta muted">нет сравнения</span>
                <span class="metric-delta-label">${label}</span>
            </div>
        `;
    }

    const sign = delta > 0 ? "+" : "";
    const cls = delta > 0 ? "delta-up" : (delta < 0 ? "delta-down" : "delta-neutral");
    const diffSign = diff > 0 ? "+" : "";
    const diffText = ` (${diffSign}${formatMetricNumber(diff, digits)}${unit ? " " + unit : ""})`;

    return `
        <div class="metric-delta-row">
            <span class="metric-delta ${cls}">${sign}${delta.toFixed(0)}%${diffText}</span>
            <span class="metric-delta-label">${label}</span>
        </div>
    `;
}

// Карточка метрики со значением за последний месяц периода и тремя
// дельтами (к прошлому месяцу / к среднему за период / к началу периода) —
// общий формат, переиспользуемый на «Графиках» и «Своде» «Анализа по
// клиентам» (см. DESIGN.md, паттерн .metric-card).
function buildMetricCard(labels, valueArr, label, digits = 2, unit = "") {
    const lastIndex = labels.length - 1;
    const prevIndex = lastIndex - 1;

    const current = Number(valueArr?.[lastIndex] ?? 0);
    const prev = prevIndex >= 0 ? Number(valueArr?.[prevIndex] ?? 0) : null;
    const first = Number(valueArr?.[0] ?? 0);
    const average = metricCalcAverage((valueArr || []).slice(0, lastIndex));

    const prevDelta = metricCalcDelta(current, prev);
    const avgDelta = metricCalcDelta(current, average);
    const firstDelta = metricCalcDelta(current, first);

    const prevDiff = current - (prev || 0);
    const avgDiff = current - (average || 0);
    const firstDiff = current - first;

    return `
        <div class="metric-card">
            <div class="metric-label">${label}</div>
            <div class="metric-value">${formatMetricNumber(current, digits)} ${unit}</div>
            <div class="metric-period">за ${labels[lastIndex]}</div>

            <div class="metric-delta-wrap">
                ${metricFormatDelta(
                    prevDelta,
                    prevIndex >= 0
                        ? `к прошлому месяцу (${labels[prevIndex]})`
                        : "к прошлому месяцу",
                    prevDiff,
                    digits,
                    unit
                )}

                ${metricFormatDelta(
                    avgDelta,
                    `к среднему за период`,
                    avgDiff,
                    digits,
                    unit
                )}

                ${metricFormatDelta(
                    firstDelta,
                    `к началу периода (${labels[0]})`,
                    firstDiff,
                    digits,
                    unit
                )}
            </div>
        </div>
    `;
}
