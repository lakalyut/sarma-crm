// Единые подписи и цвета графиков. Один показатель имеет один цвет на разных страницах.
(function () {
    const styles = getComputedStyle(document.documentElement);
    const token = name => styles.getPropertyValue(name).trim();
    const colors = {
        weight: token('--chart-weight'), qty: token('--chart-qty'),
        sku_count: token('--chart-sku'), sku_total: token('--chart-extra'), total_sku: token('--chart-extra'),
        unique_sku: token('--chart-sku'), sku_per_client: token('--chart-neutral'),
        clients: token('--chart-clients'), unique_clients: token('--chart-clients')
    };
    const palette = ['--chart-weight', '--chart-qty', '--chart-sku', '--chart-clients', '--chart-extra', '--chart-neutral'].map(token);
    window.PulseCharts = { palette, metricColor: metric => colors[metric] || palette[0] };
    if (!window.Chart?.defaults || !Chart.register) return;
    Chart.defaults.color = token('--text-muted');
    Chart.defaults.borderColor = token('--border');
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.tooltip.backgroundColor = token('--text-strong');
    Chart.defaults.plugins.tooltip.padding = 12;
    Chart.defaults.elements.line.borderWidth = 2;
    Chart.defaults.elements.point.radius = 2;
    Chart.defaults.elements.point.hoverRadius = 4;
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
