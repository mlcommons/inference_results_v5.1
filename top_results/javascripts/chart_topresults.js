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

let chart1 = null, chart2 = null, chart3 = null;

function extractDataFromTable(tableId, colIndex) {
    var data = [];
    $(tableId + " tbody tr td:nth-child(" + colIndex + ")").each(function() {
        if (!($(this).is(":hidden"))) {
            data.push($(this).text());
        }
    });
    return data;
}

function prepareChartData(location, models, performance, additional_metric, accuracy) {
    var modelsData = {}, modelsData2 = {}, modelsCount = {}, modelsData3 = [];
    var locationIndex = {}, locCount = 0;

    location.forEach(function(loc) {
        if (!(loc in locationIndex)) {
            locationIndex[loc] = locCount++;
        }
    });

    models.forEach(function(model) {
        modelsData[model] = [];
        if (additional_metric.length > 0) modelsData2[model] = [];
        modelsCount[model] = 0;
    });

    for (var i = 0; i < location.length; i++) {
        var dataPoint = {
            x: locationIndex[location[i]],
            y: parseFloat(performance[i]),
            label: location[i],
            name: location[i],
            indexLabelPlacement: "inside",
            indexLabelOrientation: "vertical",
            indexLabelMaxWidth: 200,
            indexLabelWrap: true
        };

        modelsData[models[0]].push(dataPoint);
        if (additional_metric[i]) {
            var additionalDataPoint = structuredClone(dataPoint);
            additionalDataPoint['y'] = parseFloat(additional_metric[i]);
            modelsData2[models[0]].push(additionalDataPoint);
        }

        if (accuracy[i]) {
            var accuracyDataPoint = structuredClone(dataPoint);
            accuracyDataPoint['x'] = accuracyDataPoint['y'];
            accuracyDataPoint['y'] = parseFloat(accuracy[i]);
            accuracyDataPoint['label'] += "," + models[0];
            accuracyDataPoint['name'] += "," + models[0];
            accuracyDataPoint['indexLabeli'] = accuracyDataPoint['x'];
            modelsData3.push(accuracyDataPoint);
        }

        modelsCount[models[0]]++;
    }

    return { modelsData, modelsData2, modelsData3 };
}

function renderChart(chartContainer, title, yAxisTitle, data) {
    return new CanvasJS.Chart(chartContainer, {
        title: {
            text: title
        },
        subtitles: [{
            text: "",
            fontSize: 40,
            verticalAlign: "center",
            dockInsidePlotArea: true,
            fontColor: "rgba(0,0,0,0.1)"
        }],
        legend: {
            cursor: "pointer"
        },
        axisX: {
            intervalType: String,
            valueFormatString: " ",
            labelAngle: 0,
            labelTextAlign: "center",
            labelFormatter: function(e) {
                return ("" + e.label).substring(0, 100);
            }
        },
        axisY: {
            crosshair: {
                enabled: true
            },
            title: yAxisTitle
        },
        data: data
    });
}

function drawPerfCharts() {
    var location = extractDataFromTable("#results", 1);
    var system_names = extractDataFromTable("#results", 3);
    var framework = extractDataFromTable("#results", 6);
    var performance = extractDataFromTable("#results", perfcolumnindex);
    var additional_metric = extractDataFromTable("#results", perfcolumnindex + 1);
    var models = openmodel ? extractDataFromTable("#results", 7) : [model];
    var accuracy = openmodel ? extractDataFromTable("#results", 8) : [];

    var { modelsData, modelsData2, modelsData3 } = prepareChartData(location, models, performance, additional_metric, accuracy);

    var chart1Data = Object.keys(modelsData).map(function(key) {
        return { showInLegend: true, name: key, dataPoints: modelsData[key] };
    });

    var chart2Data = Object.keys(modelsData2).map(function(key) {
        return { showInLegend: true, name: key, dataPoints: modelsData2[key] };
    });

    var chart3Data = accuracy.length > 0 ? [{
        showInLegend: true,
        type: "scatter",
        name: "SUT,model",
        dataPoints: modelsData3
    }] : [];

    chart1 = renderChart("chartContainer1", chart1title, chart1ytitle, chart1Data);
    chart1.render();

    if (additional_metric.length > 0) {
        chart2 = renderChart("chartContainer2", chart2title, chart2ytitle, chart2Data);
        chart2.render();
    } else {
        chart2 = null;
    }

    if (accuracy.length > 0) {
        chart3 = renderChart("chartContainer3", chart3title, chart3ytitle, chart3Data);
        chart3.render();
    } else {
        chart3 = null;
    }
}


$(document).ready(function() {
    if (document.getElementById("printChart1")) {
        $("#printChart1").on("click", () => chart1.exportChart({ format: "png" }));
    }
    if (document.getElementById("printChart2")) {
        $("#printChart2").on("click", () => chart2.exportChart({ format: "png" }));
    }
    if (document.getElementById("printChart3")) {
        $("#printChart3").on("click", () => chart3.exportChart({ format: "png" }));
    }
});

$(document).on("click", "thead th", function() {
    drawPerfCharts();
});
