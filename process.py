# Copyright 2024-25 MLCommons. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =============================================================================


import json
import os

# Gets unique value from data based on particular key
# For keys other than System, returns list 
# and for system, it returns dictionary(id as key and 
# submitter: system as value)
def getuniquevalues(data, key, filters = {}):
    if str(key) == "System":
        result = {}
        for item in data:
            mismatch = False
            for fkey,value in filters.items():
                if item[fkey] != value:
                    mismatch = True
                    break
            if not mismatch:
                system = item.get("System")
                submitter = item.get("Submitter")
                id = item.get("ID")
                result[id] = f"{submitter}: {system}"
        return result
    uniquevalues = []
    for item in data:
        mismatch = False
        for fkey,value in filters.items():
            if item[fkey] != value:
                mismatch = True
        if not mismatch:
            if item.get(key) and item.get(key) not in uniquevalues:
                uniquevalues.append(item[key])
    return uniquevalues

with open('summary_results.json') as f:
    data = json.load(f)
filters = {
    "Suite": "datacenter",
    "Category": "closed"
}
models_all = getuniquevalues(data, "Model", filters)
models_all.insert(0, "All models")
systems = getuniquevalues(data, "System", filters)
#print(models_all)
#print(platforms)


def filterdata(data, keys, values):
    filtered_data = []
    for item in data:
        mismatch = False
        for key,value in zip(keys, values):
            if item.get(key) != value:
                mismatch = True
                break
        if not mismatch:
            filtered_data.append(item)
    return filtered_data

def construct_table(scenario, models, data1, data2, is_power, results1, results2):
    # Initialize the HTML table with the header
    html = f'<div id="results_table_{scenario}"> <table class="tablesorter" id="results_{scenario}">'
    html += "<thead> <tr>"
    
    # Table header
    tableheader = f"""
        <th>Model</th>
        <th>{data1}</th>
        <th>{data2}</th>
        <th>Performance Delta</th>"""
    
    if is_power:
        tableheader += """
        <th>Power 1</th>
        <th>Power 2</th>
        <th>Power Delta</th>
        <th>Power Efficiency 1</th>
        <th>Power Efficiency 2</th>
        <th>Power Efficiency Delta</th>"""
    
    tableheader += "</tr>"
    
    # Add header and footer
    html += tableheader
    html += "</thead>"
    #html += f"<tfoot> <tr>{tableheader}</tr></tfoot>"
    
    # Initialize performance title (not used in the original PHP code, but included for completeness)
    performance_title = "Samples per Second"
    
    # Generate table rows
    for row in models:
        html += "<tr>"
        html += f"<td class='model'>{row}</td>"
        
        perf1 = round(results1[row]['Performance_Result'], 1)
        perf2 = round(results2[row]['Performance_Result'], 1)
        
        if perf2:
            perfdelta = round((1 - (perf1 / perf2)),4) * 100
            perfdelta = round(perfdelta, 1)
        else:
            perfdelta = ""
        
        html += f"<td class='col-result'>{perf1}</td>"
        html += f"<td class='col-result'>{perf2}</td>"
        html += f"<td class='col-result'>{perfdelta}%</td>"
        
        if is_power:
            pow1 = results1[row]['Power_Result']
            pow2 = results2[row]['Power_Result']
            
            if pow2:
                powdelta = round(((1 - pow1 / pow2)), 4) * 100
            else:
                powdelta = ""
            
            if pow1:
                peff1 = round(perf1 / pow1, 5)
            else:
                peff1 = ""
            
            if pow2:
                peff2 = round(perf2 / pow2, 5)
            else:
                peff2 = ""
            
            html += f"<td class='col-result'>{pow1}</td>"
            html += f"<td class='col-result'>{pow2}</td>"
            html += f"<td class='col-result'>{powdelta}%</td>"
            html += f"<td class='col-result'>{peff1}</td>"
            html += f"<td class='col-result>{peff2}</td>"
            
            if peff2:
                peffdelta = round(((1 - peff1 / peff2)), 4) * 100
            else:
                peffdelta = ""
            
            html += f"<td>{peffdelta}%</td>"
        
        html += "</tr>"
    
    html += "</table></div>"
    
    return html


def process_scenarios(system1, system2, sysversion1, sysversion2, modelfilterstring):
    scenarios = ["Offline", "Server", "Interactive", "SingleStream", "MultiStream"]
    ytitle_scenarios = {
        "Offline": "Samples per Second",
        "Server": "Samples per Second",
        "Interactive": "Samples per Second",
        "SingleStream": "Latency per sample in milliseconds",
        "MultiStream": "Latency per query of 8 samples in milliseconds",
    }
    content = {}
    content['custom_0'] = """
        <script type='text/javascript'>
        var data1 = {}, data2 = {}, draw_power = {}, draw_power_efficiency = {}, ytitle = {}, sortcolumnindex, perfsortorder;
        </script>
    """
    
    customid = 1
    for scenario in scenarios:
        keys = [ "Scenario", "System", "version" ]
        values = [ scenario, system1, sysversion1 ]
        result1 = filterdata(data, keys, values)
        content[f'custom_{customid}'] = f""
        
        values = [ scenario, system2, sysversion2 ]
        result2 = filterdata(data, keys, values)
        result2 = filterdata(data, keys, values)
        if len(result1) == 0 or len(result2) == 0:
            display_string=f"""style="display:none"
            """
        else:
            display_string =""
            
        
        is_power = len(result2) > 0 and (result2[0]['has_power'])
        power_string = "true" if is_power else "false"
        
        data1_str = f"{sysversion1}: {system1}"
        data2_str = f"{sysversion2}: {system2}"
        ytitle = ytitle_scenarios[scenario]
        
        content[f'custom_{customid}'] = f"""
        <script type='text/javascript'>
        data1['{scenario}'] = '{data1_str}', data2['{scenario}'] = '{data2_str}', draw_power['{scenario}'] = {power_string}, draw_power_efficiency['{scenario}'] = {power_string}, is_power = {power_string},
        ytitle['{scenario}'] = '{ytitle}',
        sortcolumnindex = 4, perfsortorder = 1;
        </script>
        """
        
        models = []
        result2_models = [row['Model'] for row in result2]
        for row in result1:
            if row['Model'] not in models and row['Model'] in result2_models:
                models.append(row['Model'])
        
        results1 = {model: row for model in models for row in result1 if row['Model'] == model}
        results2 = {model: row for model in models for row in result2 if row['Model'] == model}
        
        tableposthtml = """
            <!-- pager -->
            <div class="pager1">
            <img src="https://mottie.github.io/tablesorter/addons/pager/icons/first.png" class="first"/>
            <img src="https://mottie.github.io/tablesorter/addons/pager/icons/prev.png" class="prev"/>
            <span class="pagedisplay"></span> <!-- this can be any element, including an input -->
            <img src="https://mottie.github.io/tablesorter/addons/pager/icons/next.png" class="next"/>
            <img src="https://mottie.github.io/tablesorter/addons/pager/icons/last.png" class="last"/>
            <select class="pagesize" title="Select page size">
            <option selected="selected" value="10">10</option>
            <option value="20">20</option>
            <option value="30">30</option>
            <option value="all">All</option>
            </select>
            <select class="gotoPage" title="Select page number"></select>
            </div>
        """
        
        html = f"""<div id="{scenario}" {display_string}> <h3 id="table_header_{scenario}">Comparing {scenario} scenario for {data1_str} and {data2_str}</h3>""" + tableposthtml
        htmltable = construct_table(scenario, models, data1_str, data2_str, is_power, results1, results2)
        html += htmltable
        html += tableposthtml
        
        content[f'custom_{customid}'] += html
        
        resultjson = json.dumps(result1)  # or any appropriate variable
        
        content[f'custom_{customid}'] += f"""
            <div id="chartContainer{scenario}1" class="bgtext" style="height: 370px; width: 100%;"></div>
            <button class="btn btn-primary"  id="printChart{scenario}1">Download</button>
        """
        content[f'custom_{customid}'] += f"""
            <div id="chartContainer{scenario}2" class="bgtext power-content" style="height: 370px; width: 100%;"></div>
            <button class="btn btn-primary power-content"  id="printChart{scenario}2">Download</button>
            <div id="chartContainer{scenario}3" class="bgtext power-content" style="height: 370px; width: 100%;"></div>
            <button class="btn btn-primary power-content"  id="printChart{scenario}3">Download</button>
        """
        
        content[f'custom_{customid}'] += f"""
        <hr>
        </div>
        """
        
        customid += 1
    
    return content


#print(data)
def generate_html_form(platforms, models_all, data1=None, data2=None, modelsdata=None, categories=None):
    # Setting default values if not provided
    if not data1:
        data1 = ''
    if not data2:
        data2 = ''
    if not modelsdata:
        modelsdata = 'All models'

    # Create select options for system 1 and system 2
    def generate_select_options(options, selected_value):
        html = ""
        #print(options)
        for key, value in options.items():
            selected = 'selected' if value == selected_value else ''
            html += f"<option value='{key}' {selected}>{value}</option>\n"
        return html

    system1_options = generate_select_options(systems, data1)
    system2_options = generate_select_options(systems, data2)
    category_options = generate_select_options(categories, "datacenter")

    # Create select options for models
    models_options = generate_select_options(models_all, modelsdata)

    # Generate the HTML for the form
    html_form = f"""
    <form id="compareform"  method="post" action="">
        <h3>Compare Results</h3>

        <div class="form-field">
            <label for="system1">System 1</label>
            <select id="system1" name="system1" class="col">
                {system1_options}
            </select>
        </div>

        <div class="form-field">
            <label for="system2">System 2</label>
            <select id="system2" name="system2" class="col">
                {system2_options}
            </select>
        </div>

        <div class="form-field">
            <label for="category">Category</label>
            <select id="category" name="category" class="col">
                {category_options}
            </select>
        </div>
        
        <div class="form-field">
            <label for="models">Models</label>
            <select id="models" name="models[]" class="col" multiple>
                {models_options}
            </select>
        </div>

        <div class="form-field">
            <button type="submit" name="okthen" value="1" id="compare_results">Compare SUTs</button>
        </div>
    </form>
    """

    return html_form

system1 = "1xMI300X_2EPYC-937F"
system2 = "8xMI300X_2EPYC-937F"
sysversion1 = "v4.1"
sysversion2 = "v4.1"
modelfilterstring = ""

content = process_scenarios(system1, system2, sysversion1, sysversion2, modelfilterstring)

out_html = ""

for key,value in content.items():
    out_html += "\n" + value

out_html += """
<script type="text/javascript" src="javascripts/init_tablesorter.js">
</script>
"""

out_html += """
<script type="text/javascript" src="javascripts/chart_compare.js">
</script>
<script type="text/javascript" src="javascripts/compare_results.js">
</script>
"""



#print(content)
data1 = None
data2 = None
modelsdata = None
models_data = {v:k for v,k in enumerate(models_all)}
categories = {v:k for v,k in enumerate(["Datacenter", "Edge"])}
# Generate the HTML form
html_form = generate_html_form(systems, models_data, data1, data2, modelsdata, categories)

# Output the generated HTML
out_html = f"""---
hide:
  - toc
---

<html>
{out_html}{html_form}
</html>
"""

out_path = os.path.join("docs", "compare", "index.md")

if not os.path.exists(os.path.dirname(out_path)):
    os.makedirs(os.path.dirname(out_path))

with open(out_path, "w") as f:
    f.write(out_html)

#print(out_html)
