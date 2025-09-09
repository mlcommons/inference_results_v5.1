/* Copyright 2024-25 MLCommons. All Rights Reserved.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
==============================================================================*/


// Variables for storing chart objects
const charts = {
    performance: {},
    power: {},
    efficiency: {}
};

// Available scenarios for analysis
const analysisScenarios = ["Offline", "Server", "Interactive", "SingleStream", "MultiStream"];

function initializeCharts() {
    analysisScenarios.forEach(scenario => generateChartsForScenario(scenario));
}

function generateChartsForScenario(scenario) {
    const chartData = collectChartData(scenario);

    if (!chartData) return;

    // Draw the charts
    drawPerformanceChart(scenario, chartData.performance, chartData.modelNames);
    if (draw_power[scenario]) drawPowerChart(scenario, chartData.power);
    if (draw_power_efficiency[scenario]) drawEfficiencyChart(scenario, chartData.efficiency);
}

function collectChartData(scenario) {
    const tableId = `#results_${scenario}`;
    const chartData = {
        performance: { values1: [], values2: [] },
        power: { values1: [], values2: [] },
        efficiency: { values1: [], values2: [] },
        modelNames: []
    };

    // If the table is not available, skip this scenario
    if (!$(tableId).length) return null;

    // Collect data from the table
    $(`${tableId} tbody tr`).each(function() {
        const row = $(this);
        chartData.modelNames.push(row.find("td:nth-child(1)").text());

        if (!row.find("td:nth-child(2)").is(":hidden")) chartData.performance.values1.push(parseFloat(row.find("td:nth-child(2)").text()));
        if (!row.find("td:nth-child(3)").is(":hidden")) chartData.performance.values2.push(parseFloat(row.find("td:nth-child(3)").text()));
        if (!row.find("td:nth-child(5)").is(":hidden")) chartData.power.values1.push(parseFloat(row.find("td:nth-child(5)").text()));
        if (!row.find("td:nth-child(6)").is(":hidden")) chartData.power.values2.push(parseFloat(row.find("td:nth-child(6)").text()));
        if (!row.find("td:nth-child(8)").is(":hidden")) chartData.efficiency.values1.push(parseFloat(row.find("td:nth-child(8)").text()));
        if (!row.find("td:nth-child(9)").is(":hidden")) chartData.efficiency.values2.push(parseFloat(row.find("td:nth-child(9)").text()));
    });

    return chartData;
}

function drawPerformanceChart(scenario, { values1, values2 }, models) {
    const chartData = createChartData(scenario, values1, values2, models);

    charts.performance[scenario] = new CanvasJS.Chart(`chartContainer${scenario}1`, {
        title: { text: "Performance Comparison" },
        subtitles: [{
            text: "",
            fontSize: 40,
            verticalAlign: "center",
            dockInsidePlotArea: true,
            fontColor: "rgba(0,0,0,0.1)"
        }],
        axisX: {
            intervalType: "String",
            valueFormatString: " ",
            labelAngle: 135,
            labelTextAlign: "center",
            labelMaxWidth: 100,
            labelFormatter: function(e) {
	        if (!e.label) return "";
                let label = e.label.toString();
                let maxLength = 40;  // Max characters per line
                let wrappedLabel = '';

                // Wrap the label by adding \n at every maxLength interval
                for (let i = 0; i < label.length; i += maxLength) {
                    wrappedLabel += label.substring(i, i + maxLength) + "\n";
                }
                return wrappedLabel;
            }
        },
        axisY: {
            title: ytitle[scenario],
            minimum: 0
        },
        data: chartData
    });

    charts.performance[scenario].render();
}

function drawPowerChart(scenario, { values1, values2 }, models) {
    const chartData = createChartData(scenario, values1, values2, models);

    charts.power[scenario] = new CanvasJS.Chart(`chartContainer${scenario}2`, {
        title: { text: "Power Comparison" },
        axisX: {
            labelFormatter: e => (""+e.label).substring(0, 75),
            labelAngle: 0
        },
        axisY: {
            title: "Average Power (Watts)"
        },
        data: chartData
    });

    charts.power[scenario].render();
}

function drawEfficiencyChart(scenario, { values1, values2 }, models) {
    const chartData = createChartData(scenario, values1, values2, models);

    charts.efficiency[scenario] = new CanvasJS.Chart(`chartContainer${scenario}3`, {
        title: { text: "Power Efficiency" },
        axisX: {
            labelFormatter: e => (""+e.label).substring(0, 75),
            labelAngle: 0
        },
        axisY: {
            title: "Samples per Joule"
        },
        data: chartData
    });

    charts.efficiency[scenario].render();
}

function createChartData(scenario, values1, values2, models) {
    return [
        {
            showInLegend: true,
            type: "column",
            name: data1[scenario],
            dataPoints: values1.map((value, index) => ({ x: index, y: value, label: models[index]}))
        },
        {
            showInLegend: true,
            type: "column",
            name: data2[scenario],
            dataPoints: values2.map((value, index) => ({ x: index, y: value, label: models[index] }))
        }
    ];
}

// Event listeners for print functionality
function setupPrintListeners() {
    analysisScenarios.forEach(scenario => {
        if ($("#printChart" + scenario + "1").length) {
            $("#printChart" + scenario + "1").on("click", () => exportChart(scenario, 'performance'));
        }
        if (draw_power[scenario] && $("#printChart" + scenario + "2").length) {
            $("#printChart" + scenario + "2").on("click", () => exportChart(scenario, 'power'));
        }
        if (draw_power_efficiency[scenario] && $("#printChart" + scenario + "3").length) {
            $("#printChart" + scenario + "3").on("click", () => exportChart(scenario, 'efficiency'));
        }
    });
}

function exportChart(scenario, chartType) {
    charts[chartType][scenario].exportChart({ format: "png" });
}

// Initialize the charts and event listeners
initializeCharts();
setupPrintListeners();
