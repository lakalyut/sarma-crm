// Единые подписи и цвета графиков. Один показатель имеет один цвет на разных страницах.
(function () {
    const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const colors = {
        weight: token('--chart-weight'), qty: token('--chart-qty'),
        sku_count: token('--chart-sku'), sku_total: token('--chart-extra'), total_sku: token('--chart-extra'),
        unique_sku: token('--chart-sku'), sku_per_client: token('--chart-neutral'),
        clients: token('--chart-clients'), unique_clients: token('--chart-clients')
    };
    const paletteTokens = ['--chart-weight', '--chart-qty', '--chart-sku', '--chart-clients', '--chart-extra', '--chart-neutral'];
    const palette = paletteTokens.map(token);
    window.PulseCharts = { palette, metricColor: metric => colors[metric] || palette[0] };
    if (!window.Chart?.defaults || !Chart.register) return;
    Chart.defaults.color = token('--text-muted');
    Chart.defaults.borderColor = token('--border');
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.tooltip.backgroundColor = token('--chart-tooltip-bg');
    Chart.defaults.plugins.tooltip.padding = 12;
    Chart.defaults.elements.line.borderWidth = 2;
    Chart.defaults.elements.point.radius = 2;
    Chart.defaults.elements.point.hoverRadius = 4;
    document.addEventListener("pulse-theme-change", () => {
        const previous = [...palette];
        palette.splice(0, palette.length, ...paletteTokens.map(token));
        for (const metric of Object.keys(colors)) {
            colors[metric] = palette[previous.indexOf(colors[metric])];
        }
        Chart.defaults.color = token('--text-muted');
        Chart.defaults.borderColor = token('--border');
        Chart.defaults.plugins.tooltip.backgroundColor = token('--chart-tooltip-bg');

        for (const chart of Object.values(Chart.instances)) {
            for (const dataset of chart.data.datasets) {
                for (const property of ['borderColor', 'backgroundColor', 'pointHoverBackgroundColor']) {
                    const value = dataset[property];
                    if (typeof value !== 'string') continue;
                    const index = previous.indexOf(value.slice(0, 7));
                    if (index >= 0) dataset[property] = palette[index] + value.slice(7);
                }
            }
            chart.update('none');
        }
    });
    Chart.register({
        id: 'pulseTheme',
        beforeInit(chart) {
            chart.data.datasets.forEach((dataset, index) => {
                const color = dataset.pulseMetric ? window.PulseCharts.metricColor(dataset.pulseMetric) : palette[index % palette.length];
                dataset.borderColor ??= color;
                dataset.backgroundColor ??= color + (chart.config.type === 'bar' ? 'b3' : '20');
            });
        }
    });
})();
