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


var allData = [];

$( document ).on( "click", "#results thead th", function() {
    drawPerfCharts();
});

var device_column_name = "Accelerator";
var device_count_column_name = "#a";
var additional_metric_column_name = "";
var version = results_version;
var openmodel=false;
var sortcolumnindex = 6;
var perfcolumnindex = 7; // starting from 1
var chart1title = ''; //defined when selecting metric
var chart2title = '';
var chart3title = 'Accuracy vs Performance';
var chart1ytitle = '';
var chart2ytitle = '';
var chart3ytitle = 'Accuracy';
var chart3xtitle = chart1ytitle;
var perfsortorder = 1;
var model='llama2-70b-99.9';
$('#chartContainer3').hide();
$('#printChart3').hide();
$('#chartContainer2').hide();
$('#printChart2').hide();

function animateToTop() {
$('html, body').animate({
            scrollTop: 0
        }, 'slow');
}
function updateContent(myData) {
    //$("#topresults_table_wrapper").focus();
    model = $("#model").val();
    scenario = $("#scenario").val();
    division = $("#division").val(); 
    category = $("#category").val(); 
    metric = $("#metric").val();
    metric_str = metric.replace("_", " ");
    //updateScenarioUnits(myData);
    if(myData.length == 0) {
        $("#topresults_heading").text(`No ${model} results in ${category} category, ${division} division for ${metric_str} metric`);
        $("#topresults_table_wrapper").hide();
        $(".chart").hide();
        $(".btn-chart").hide();
        $("button.print").hide();
        animateToTop();
        return;
    }
    $("#topresults_table_wrapper").show();
    $("#topresults_heading").text(`${model} results in ${category} category, ${division} division, ${scenario} scenario for ${metric_str} metric`);
    tablehtml = constructTable(division, scenario, model, metric, myData);
    //console.log(division+scenario);
    //console.log(tablehtml);
    document.getElementById("topresults_table_wrapper").innerHTML = tablehtml;
    tableSorterInit();
    
    //$('table').tablesorter();
    //$("table").trigger("updateAll");
    $('table')
    .tablesorter()
// bind to sort events
    .bind('tablesorter-ready', function(e, table) {
        // do something after the 'refreshWidgets' has refreshed
        //drawPowerChart();
        drawPerfCharts();
    });
    animateToTop();
}

$(document).ready(function() {

    //console.log("The page is fully loaded.");
});


function constructTable(division, scenario, model, metric, result) {
    //console.log(metric);
    let html = tableposhtml;
    let theader = `
        <th>ID</th>
        <th>System</th>
        <th>Submitter</th>
        <th>${device_column_name}</th>
        <th>${device_count_column_name}</th>
        <th>Framework</th>
    `;

    if (division == "open") {
        openmodel = true;
        theader += `
            <th>Model</th>
            <th>Accuracy</th>
        `;
    }
    theader += `<th>Performance</th>`;

    if (additional_metric_column_name) {
        theader += `<th>${additional_metric_column_name}</th>`;
    }

    html += `
        <table class="tablesorter" id="results">
            <thead>
                <tr>${theader}</tr>
            </thead>
            <tfoot>
                <tr>${theader}</tr>
            </tfoot>
            <tbody>
    `;

    const performance_title = "Samples per Second";

    result.forEach(row => {
        //console.log(row);
        let cores = 0;
        html += "<tr>";
        const platform = row.Platform;
        const resultid = row.ID;
	// just for backward compatability with 4.0
	let system_json_link = row['Details'].replace("/results/", "/systems/").replace("submissions_inference_4.0", "inference_results_v4.0") + ".json"
        //const location = `https://github.com/mlcommons/inference_results_${version}/tree/main/${row.Location}`;
        // html += `<td title="${resultid}" class='location'><a target="_blank" href="${system_json_link}">${platform}</a></td>`;
        html += `<td title="${platform}">${row.ID}</td>`;
        html += `<td title="${platform}"><a target="_blank" href="${system_json_link}">${row.System}</a></td>`;
        html += `<td>${row.Submitter}</td>`;

        if (!(row["a#"] > 0)) {
            cores = row.Nodes * row.host_processors_per_node * row.host_processor_core_count;
            html += `<td>${row.Processor}</td>`;
            html += `<td>${cores}</td>`;
        } else {
            acc_nums = row.Nodes * row["a#"];
            html += `<td>${row.Accelerator}</td>`;
            html += `<td>${acc_nums}</td>`;
        }

        html += `<td>${row.Software}</td>`;

        if (division == "open") {
            html += `<td>${row.UsedModel}</td>`;
            acc__ = row.Accuracy.split("  ")
            acc_ = acc__[0].split(":")
            acc = parseFloat(acc_[1])

            html += `<td>${acc}</td>`;
        }

        html += `<td class='performance' title='${performance_title}'>${row.Performance_Result.toFixed(2)}</td>`;

        if (additional_metric_column_name) {
            let value;
            if (metric === "power_efficiency") {
                let power_efficiency;
                if (scenario === "Offline" || scenario === "Server" || scenario === "Interactive") {
                    power_efficiency = (row.Performance_Result / row.Power_Result).toFixed(2);
                } else if (scenario === "SingleStream") {
                    power_efficiency = (1000 / row.Power_Result).toFixed(2);
                } else if (scenario === "MultiStream") {
                    power_efficiency = (8000 / row.Power_Result).toFixed(2);
                }
                html += `<td class='power' title='Total Watts: ${row.Power_Result.toFixed(0)}'>${power_efficiency}</td>`;
            } else if (metric === "performance_per_accelerator") {
                //console.log(row.Performance_Result);
                value = row["a#"] > 0 ? (row.Performance_Result / (row['Nodes']*row["a#"])).toFixed(2) : "0";
                html += `<td class='power'>${value}</td>`;
            } else if (metric === "performance_per_core") {
                value = (row.Performance_Result / cores).toFixed(2);
                html += `<td class='power'>${value}</td>`;
            }
        }

        html += "</tr>";
    });

    html += `
            </tbody>
        </table>
    `;

    html += tableposhtml;

    return html;

}


function updateFilters(myData) {
        var platforms = getUniqueValuesCombined(myData, " : ", [ "version", "Submitter", "System" ]);
        platforms.unshift("All systems");
        buildSelectOption(platforms, "filter_systems", "All systems");
	var devices = getUniqueValuesCombined(myData, " x ", [ "Accelerator", "a#" ]);
        devices.unshift("All devices");
        buildSelectOption(devices, "filter_devices", "All devices");
}



$(document).ready(function() {
    allData = [];
    readAllData().then(function(global_data) {
        //console.log(allData);
        allData = global_data;
        keys = [ "Suite", "Category" ];
        values = [ "datacenter", "closed" ];
        myData = filterData(allData, keys, values);
        var models = getUniqueValues(myData, "Model");
        scenario = "Offline";
        division = "closed"; 
        category = "datacenter";
        keys = ["Model", "Scenario"];
        values = ["llama2-70b-99.9", scenario];
        myData = filterData(myData, keys, values);
        //console.log(myData);
        $("#model").append('<option selected value="llama2-70b-99.9">Llama 2</option>');
        var scenarios = validScenarios["datacenter"];// getUniqueValues(myData, "Scenario");
        model = $("#model").val();
        //updateScenarioUnits(myData);
        buildSelectOption(models, "model", model);
        buildSelectOption(scenarios, "scenario", scenario);

	updateFilters(myData);

	charttitlesuffix = ` for ${model} ${scenario} scenario in ${division} division ${category} category`;
        chart1title = "Performance " + charttitlesuffix;
       // chart2title = "Performance per accelerator " + charttitlesuffix;
        //chart2ytitle = "Samples per second per accelerator";
        updateContent(myData);
    }).catch(function(error) {
        console.error(error);
    });


    $('.myFilter').on('change', function() {
        var category = $('#category').val();
        var division = $('#division').val();
        var availability = $('#availability').val();
        var model = $('#model').val();
        var scenario = $('#scenario').val();
        keys = [ "Suite", "Category" ];
        values = [ category, division ];
        if(availability != 'all') {
            keys.push("Availability");
            values.push(availability);
        }
        //console.log(allData);
        myData = filterData(allData, keys, values);
        //console.log(scenario);
        var models = getUniqueValues(myData, "Model");
        var scenarios = validScenarios[category];// getUniqueValues(myData, "Scenario");
	buildSelectOption(models, "model", model);
        buildSelectOption(scenarios, "scenario", scenario);
        
	updateFilters(myData);
    });


    $('#model').on('change', function() {
        var category = $('#category').val();
        var division = $('#division').val();
        var availability = $('#availability').val();
        var model = $('#model').val();
        keys = [ "Suite", "Category", "Model" ];
        values = [ category, division, model ];
        if(availability != 'all') {
            keys.push("Availability");
            values.push(availability);
        }
        //console.log(allData);
        myData = filterData(allData, keys, values);
        //console.log(category+division+scenario);
        var scenarios = getUniqueValues(myData, "Scenario");
        buildSelectOption(scenarios, "scenario", scenario);
	updateFilters(myData);
    });

    $('#resultSelectionForm').submit(function(event) {
        event.preventDefault(); // This will cancel the form submission

        // Your custom logic here
        //console.log('Form submission canceled.');
        var category = $('#category').val();
        var division = $('#division').val();
        var availability = $('#availability').val();
        var scenario = $('#scenario').val();
        var metric = $('#metric').val();
        var model = $('#model').val();
        var filter_systems = $('#filter_systems option:selected').map(function() {
            return $(this).text();
        }).get();
        /*var filter_device = $('#filter_devices option:selected').map(function() {
            return $(this).text();
        }).get();*/
        var filter_devices = $('#filter_devices option:selected').map(function() {
            return $(this).text();
        }).get();
       // var filter_device = $('#filter_devices').val();

        sortcolumnindex = 6;
        perfcolumnindex = 7; // starting from 1

        //console.log(division);
        if(division == "closed") {
            $('#chartContainer3').hide();
            $('#printChart3').hide();
        }
        else {
            $('#chartContainer3').show();
            $('#printChart3').show();
             sortcolumnindex+=2;
             perfcolumnindex+=2;
        }
        //console.log(category+division+availability+scenario+metric+model);
        keys = [ "Suite", "Category" ];
        values = [ category, division ];

        if(availability != 'all') {
            keys.push('Availability');
            values.push(availability);
        }
        //console.log(allData);
        myData = filterData(allData, keys, values);
        //console.log(scenario);
        var models = getUniqueValues(myData, "Model");

        additional_metric_column_name = "";
        if(scenario == "Offline" || scenario == "Server" || scenario == "Interactive") {
            perfsortorder = 1;
        }
        else {
            perfsortorder = 0;
        }
        charttitlesuffix = ` for ${model} ${scenario} scenario in ${division} division ${category} category`;
        keys = ["Model", "Scenario"];
        values = [model, scenario];
        extra_filter=null;

        chart1title = "Performance " + charttitlesuffix;
        $('#chartContainer1').show();
	$('#printChart1').show();
        
        if (metric === 'performance') {
            device_column_name = "Device";
            device_count_column_name = "#devices";
            additional_metric_column_name = "";
            chart1title = "Performance " + charttitlesuffix;
            $('#chartContainer2').hide();
            $('#printChart2').hide();
        } else if (metric === 'power_efficiency') {
            extra_filter = "power";
            device_column_name = "Processor";
            device_count_column_name = "Total Physical Cores";
            additional_metric_column_name = "Samples per Joule";
            chart2title = "Power efficiency " + charttitlesuffix;
            chart2ytitle = "Samples per Joule";
            sortcolumnindex = 7;
            perfsortorder = 1;
            $('#chartContainer2').show();
	    $('#printChart2').show();
        } else if (metric === 'performance_per_accelerator') {
            extra_filter = "accelerator_only";
            device_column_name = "Accelerator";
            device_count_column_name = "#a";
            //filter = " and accelerators_per_node > 0";
            if (scenario === "Offline") {
                additional_metric_column_name = "Performance per accelerator";
                chart2title = "Performance per accelerator " + charttitlesuffix;
                chart2ytitle = "Samples per second per accelerator";
                sortcolumnindex = 7;
            }
            $('#chartContainer2').show();
	    $('#printChart2').show();
       } else if (metric === 'performance_per_core') {
            extra_filter = "cpu_only";
            device_column_name = "Processor";
            device_count_column_name = "Total Physical Cores";
            if (scenario === "Offline") {
                additional_metric_column_name = "Performance per core";
                chart2title = "Performance per core " + charttitlesuffix;
                chart2ytitle = "Samples per second per core";
                sortcolumnindex = 7;
            }
            $('#chartContainer2').show();
	    $('#printChart2').show();
        }   
        myData = filterData(myData, keys, values, extra_filter);
        
        if (!filter_devices.includes("All devices")) {
            acc_names = [];
            acc_nums = [];
            for(let filter_device of filter_devices) {
                item = filter_device.split(" x ");
                acc = item[0];
                num = item[1];
                acc_names.push(acc);
                acc_nums.push(num);
            }
            myData = filterDataByAccelerators(myData, acc_names, acc_nums);
        }
         
        if (!filter_systems.includes("All systems")) {
            systems = [];
            versions = [];
            submitters = [];
            for(let filter_system of filter_systems) {
                item = filter_system.split(" : ");
                version = item[0];
                submitter = item[1];
                system = item[2];
                systems.push(system);
                versions.push(version);
                submitters.push(submitter)
            }
            myData = filterDataBySystems(myData, systems, versions, submitters);
        }


        updateContent(myData);
        //console.log(myData);
    });

});
