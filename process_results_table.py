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
import time

with open('summary_results.json') as f:
    data = json.load(f)
#print(models_all)
#print(platforms)

tableposhtml = """
<!-- pager -->
<div class="pager1 PAGER_CLASS">
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

repo_owner = os.environ.get("INFERENCE_RESULTS_REPO_OWNER", "mlcommons") 
repo_name = os.environ.get("INFERENCE_RESULTS_REPO_NAME", "inference_results_v4.1") 
repo_branch = os.environ.get("INFERENCE_RESULTS_REPO_OWNER", "main") 

def get_json_files(github_url):
    import requests
    from bs4 import BeautifulSoup

    retries = 5
    retry_delay = 2

    for attempt in range(retries):
        try:
            # Get the content of the GitHub page
            response = requests.get(github_url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find all JSON files
            #print(soup)
            # Find the <script> tag with the specific data-target attribute
            script_tag = soup.find('script', {'data-target': 'react-app.embeddedData', 'type': 'application/json'})

            if script_tag:
                # Extract the JSON content from the script tag
                json_data = script_tag.string

                # Parse the JSON string into a Python dictionary
                data = json.loads(json_data)

                # Access the parts of the JSON you are interested in
                tree_items = data.get('payload', {}).get('tree', {}).get('items', [])
                
                json_files = [a['name'] for a in tree_items if a['name'].endswith('.json')]

                return json_files
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:  # Don't wait after the last attempt
                time.sleep(retry_delay)
            else:
                print("Max retries reached. Exiting.")
                return None

def find_match(files, re_name):
    import re 
    for file in files:
        if re.match(re_name, file):
            return file
    print(re_name)
    print(files)
    return None


def getsummarydata(data, category, division):
    mydata = {}
    mycountdata = {}
    for item in data:
        if category not in item['Suite']:
            continue
        if item['Category'] != division:
            continue
        '''
        if item['Availability'] != availability:
            continue
        '''
        submitter = item['Submitter']
        if mydata.get(submitter, '') == '':
            mydata[submitter] = {}
        myid = item['ID']
        if mydata[submitter].get(myid, '') == '':
            mydata[submitter][myid] = {}
        model = item['Model']
        if mydata[submitter][myid].get(model, '') == '':
            mydata[submitter][myid][model] = {}
            mydata[submitter][myid][model]['count'] = 0
        if division == "open":
            scenario = item['Scenario']
            if mydata[submitter][myid][model].get(scenario, '') == '':
                mydata[submitter][myid][model][scenario] = 0

        mydata[submitter][myid][model]['count'] += 1

    #print(mydata)
    for submitter,value in mydata.items():
        mycountdata[submitter] = {}
        for sut, results in value.items():
            for model, model_data in results.items():
                if mycountdata[submitter].get(model, '') == '':
                    mycountdata[submitter][model] = 0
                mycountdata[submitter][model] += model_data['count']
    return mydata, mycountdata









def processdata(data, category, division, availability):

    mydata = {}
    needed_keys_model = [ "has_power", "Performance_Result", "Performance_Units", "Accuracy", "Location", "weight_data_types" ]

    needed_keys_system = [ "System", "Submitter", "Availability", "Category", "Accelerator", "a#", "Nodes", "Processor", "host_processors_per_node", "host_processor_core_count", "Notes", "Software", "Details", "Platform" ]
    for item in data:
        if category not in item['Suite']:
            continue
        if item['Category'] != division:
            continue
        if item['Availability'] != availability:
            continue
        myid = item['ID']
        if mydata.get(myid, '') == '':
            mydata[myid] = {}
        model = item['Model']
        if mydata[myid].get(model, '') == '':
            mydata[myid][model] = {}
        scenario = item['Scenario']
        if mydata[myid][model].get(scenario, '') == '':
            mydata[myid][model][scenario] = {}

        mydata[myid][model][scenario]['has_power'] = item['has_power']
        if item['has_power'] and item.get('Power_Result'):
            mydata[myid][model][scenario]['Power_Result'] = item['Power_Result']
            mydata[myid][model][scenario]['Power_Units'] = item['Power_Units']
        for key in needed_keys_model:
            mydata[myid][model][scenario][key] = item[key]
        for key in needed_keys_system:
            mydata[myid][key] = item[key]
    return mydata

models_dc = [ "llama2-70b-99", "llama2-70b-99.9", "gptj-99", "gptj-99.9", "bert-99", "bert-99.9", "stable-diffusion-xl",  "dlrm-v2-99", "dlrm-v2-99.9", "retinanet", "resnet", "3d-unet-99", "3d-unet-99.9"  ]
models_edge = [ "gptj-99", "gptj-99.9", "bert-99", "bert-99.9", "stable-diffusion-xl", "retinanet", "resnet", "3d-unet-99", "3d-unet-99.9"  ]


def get_scenario_result(data, scenario, location_pre, result_link_text):
    html = ''
    if data.get(scenario):
        github_url  = f"""{location_pre}{data[scenario]['Location'].replace("results", "measurements")}/"""
        extra_model_info = f"""Model precision: {data[scenario]['weight_data_types']}"""
                    
        html += f"""
            <td class="col-result"><a target="_blank" title="{result_link_text}{extra_model_info}" href="{location_pre}{data[scenario]['Location']}"> {round(data[scenario]['Performance_Result'],1)} </a> </td>
        """
    else:
        html += """<td class="col-result"></td>"""

    return html


def construct_table(category, division, availability):
    # Initialize the HTML table with the header
    html = f"""<div id="results_table_{availability}" class="resultstable_wrapper"> <table class="resultstable tablesorter tableclosed tabledatacenter" id="results_{availability}">"""
    html += "<thead> <tr>"

    if category == "datacenter":
        models = models_dc
    else:
        models = models_edge
    
    # Table header
    if category == "datacenter":
        tableheader = f"""
            <th id="col-id" class="headcol col-id">ID</th>
            <th id="col-system" class="headcol col-system">System</th>
            <th id="col-submitter" class="headcol col-submitter">Submitter</th>
            <th id="col-accelerator" class="headcol col-accelerator">Accelerator</th>
            <th id="col-llama2-99" colspan="2">LLAMA2-70B-99</th>
            <th id="col-llama2-99.9" colspan="2">LLAMA2-70B-99.9</th>
            <th id="col-gptj-99" colspan="2">GPTJ-99</th>
            <th id="col-gptj-99.9" colspan="2">GPTJ-99.9</th>
            <th id="col-bert-99" colspan="2">Bert-99</th>
            <th id="col-bert-99.9" colspan="2">Bert-99.9</th>
            <th id="col-sdxl" colspan="2">Stable Diffusion</th>
            <th id="col-dlrm-v2-99" colspan="2">DLRM-v2-99</th>
            <th id="col-dlrm-v2-99.9" colspan="2">DLRM-v2-99.9</th>
            <th id="col-retinanet" colspan="2">Retinanet</th>
            <th id="col-resnet50" colspan="2">ResNet50</th>
            <th id="col-3d-unet-99" colspan="1">3d-unet-99</th>
            <th id="col-3d-unet-99.9" colspan="1">3d-unet-99.9</th>
            """ 
        tableheader += "</tr>"
    
        tableheader += f"""
        <tr>
        <th class="headcol col-id"></th>
        <th class="headcol col-system"></th>
        <th class="headcol col-submitter"></th>
        <th class="headcol col-accelerator"></th>
        """
        for model in models:
            if "3d-unet" in model:
                tableheader += f"""
                <th class="col-scenario">Offline</th>
                """
            else:
                tableheader += f"""
                <th class="col-scenario">Server</th>
                <th class="col-scenario">Interactive</th>
                <th class="col-scenario">Offline</th>
                """
    else: # category == "edge":
        tableheader = f"""
            <th id="col-id" class="headcol col-id">ID</th>
            <th id="col-system" class="headcol col-system">System</th>
            <th id="col-submitter" class="headcol col-submitter">Submitter</th>
            <th id="col-accelerator" class="headcol col-accelerator">Accelerator</th>
            <th id="col-gptj-99" colspan="2">GPTJ-99</th>
            <th id="col-gptj-99.9" colspan="2">GPTJ-99.9</th>
            <th id="col-bert-99" colspan="2">Bert-99</th>
            <th id="col-bert-99.9" colspan="2">Bert-99.9</th>
            <th id="col-sdxl" colspan="2">Stable Diffusion</th>
            <th id="col-retinanet" colspan="3">Retinanet</th>
            <th id="col-resnet50" colspan="3">ResNet50</th>
            <th id="col-3d-unet-99" colspan="2">3d-unet-99</th>
            <th id="col-3d-unet-99.9" colspan="2">3d-unet-99.9</th>
            """ 
        tableheader += "</tr>"
    
        tableheader += f"""
        <tr>
        <th class="headcol col-id"></th>
        <th class="headcol col-system"></th>
        <th class="headcol col-submitter"></th>
        <th class="headcol col-accelerator"></th>
        """
        for model in models:
            tableheader += f"""
                <th class="col-scenario">Offline</th>
                <th class="col-scenario">SingleStream</th>
            """
            if  model in ["resnet", "retinanet"]:
                tableheader += f"""
                <th class="col-scenario">MultiStream</th>
            """
     
    # Add header and footer
    html += tableheader
    html += "</tr></thead>"
    html += f"<tfoot> <tr>{tableheader}</tr></tfoot>"

    mydata = processdata(data, category, division, availability)

    if not mydata:
        return None


    location_pre = f"https://github.com/{repo_owner}/{repo_name}/tree/{repo_branch}/"
    result_link_text = "See result logs"
    result_link_text = ""
    for rid in mydata:
        extra_sys_info = f"""
Processor: {mydata[rid]['Processor']}
Software: {mydata[rid]['Software']}
Cores per processor: {mydata[rid]['host_processor_core_count']}
Processors per node: {mydata[rid]['host_processors_per_node']}
Nodes: {mydata[rid]['Nodes']}
Notes: {mydata[rid]['Notes']}
        """
        a_num = mydata[rid]['a#']
        if a_num =='':
            acc = ""
        else:
            acc = f"{mydata[rid]['Accelerator']} x {int(a_num)}"
        system_json_link = f"""{mydata[rid]['Details'].replace("results", "systems")}.json"""
        html += f"""
        <tr>
        <td class="col-id headcol"> {rid} </td>
        <td class="col-system headcol" title="{extra_sys_info}"> <a target="_blank" href="{system_json_link}"> {mydata[rid]['System']} </a> </td>
        <td class="col-submitter headcol"> {mydata[rid]['Submitter']} </td>
        <td class="col-accelerator headcol"> {acc} </td>
        """

        for m in models:
            if mydata[rid].get(m):
                if category == "datacenter" and "3d-unet" not in m:#dc
                    html +=  get_scenario_result(mydata[rid][m], "Server", location_pre, result_link_text)
                    html +=  get_scenario_result(mydata[rid][m], "Interactive", location_pre, result_link_text)

                html +=  get_scenario_result(mydata[rid][m], "Offline", location_pre, result_link_text)
                
                if category == "edge": #Process SS and MS
                    html +=  get_scenario_result(mydata[rid][m], "SingleStream", location_pre, result_link_text)
                    if m in ["resnet", "retinanet"]:
                        html +=  get_scenario_result(mydata[rid][m], "MultiStream", location_pre, result_link_text)
            else:
                html += f"""
                <td></td>
                """
                if ("3d-unet" not in m and category == "datacenter") or (category == "edge"):
                    html += f"""
                    <td></td>
                    """
                if m in ["resnet", "retinanet"]  and category == "edge":
                    html += f"""
                    <td></td>
                    """


        html += f"""
        </tr>
        """
    
    html += "</table></div>"
    
    return html


def construct_summary_table(category, division):
    summary_data, count_data = getsummarydata(data, category, division)
    #print(count_data)

    if category == "datacenter":
        models = models_dc
    else:
        models = models_edge

    html  = ""
    html += """
    <div class="counttable_wrapper">
    <table class="tablesorter counttable" id="results_summary">
    <thead>
    <tr>
    <th class="count-submitter">Submitter</th>
    """
    if category == "datacenter":
        html += """
            <th id="col-llama2-99">LLAMA2-70B-99</th>
            <th id="col-llama2-99.9">LLAMA2-70B-99.9</th>
            <th id="col-gptj-99">GPTJ-99</th>
            <th id="col-gptj-99.9">GPTJ-99.9</th>
            <th id="col-bert-99">Bert-99</th>
            <th id="col-bert-99.9">Bert-99.9</th>
            <th id="col-dlrm-v2-99">Stable Diffusion</th>
            <th id="col-dlrm-v2-99">DLRM-v2-99</th>
            <th id="col-dlrm-v2-99.9">DLRM-v2-99.9</th>
            <th id="col-retinanet">Retinanet</th>
            <th id="col-resnet50">ResNet50</th>
            <th id="col-3d-unet-99">3d-unet-99</th>
            <th id="col-3d-unet-99.9">3d-unet-99.9</th>
            <th id="all-models">Total</th>
            </tr>
            </thead>
            """
    else:
        html += """
                <th id="col-gptj-99">GPTJ-99</th>
                <th id="col-gptj-99.9">GPTJ-99.9</th>
                <th id="col-bert-99">Bert-99</th>
                <th id="col-bert-99.9">Bert-99.9</th>
                <th id="col-sdxl">Stable Diffusion</th>
                <th id="col-retinanet">Retinanet</th>
                <th id="col-resnet50">ResNet50</th>
                <th id="col-3d-unet-99">3d-unet-99</th>
                <th id="col-3d-unet-99.9">3d-unet-99.9</th>
                <th id="all-models">Total</th>
                </tr>
                </thead>
        """
    total_counts = {}
    for submitter, item in count_data.items():
        html += "<tr>"
        cnt = 0

        html += f"""<td class="count-submitter"> {submitter} </td>"""
        for m in models:
            if item.get(m, '') != '':
                html += f"""<td class="col-result"> {item[m]} </td>"""
                cnt += item[m]
                if total_counts.get(m, '') == '':
                    total_counts[m] = item[m]
                else:
                    total_counts[m] += item[m]
            else:
                html += f"""<td class="col-result"> 0 </td>"""
        html += f"""<td class="col-result"> {cnt} </td>"""
        html += "</tr>"
    html += """
    <tr>
    <td class="count-submitter">Total</td>
    """
    total = 0
    for m in models:
        if total_counts.get(m, '') != '':
            html += f"""<td class="col-result"> {total_counts[m]} </td>"""
            total += total_counts[m]
        else:
            html += f"""<td class="col-result"> 0 </td>"""
    html += f"""<td class="col-result"> {total} </td>"""
    html += "</tr>"

    html += "</table></div>"
    return html

categories = { "datacenter" : "Datacenter",
              "edge": "Edge"
              }
divisions= {
        "closed": "Closed",
        "open": "Open"
        }

def generate_html_form(categories, divisions, selected_category=None, selected_division=None, with_power=None):
    # Setting default values if not provided
    if not selected_category:
        selected_category = ''
    if not selected_division:
        selected_division = ''
    if with_power is None:
        with_power = 'false'

    # Create select options for categories and divisions
    def generate_select_options(options, selected_value):
        html = ""
        for key, value in options.items():
            selected = 'selected' if key == selected_value else ''
            html += f"<option value='{key}' {selected}>{value}</option>\n"
        return html

    category_options = generate_select_options(categories, selected_category)
    division_options = generate_select_options(divisions, selected_division)

    # Generate the HTML for the form
    html_form = f"""
    <form id="resultSelectionForm" method="post" action="">
        <h3>Select Category and Division</h3>

        <div class="form-field">
            <label for="category">Category</label>
            <select id="category" name="category" class="col">
                {category_options}
            </select>
        </div>

        <div class="form-field">
            <label for="division">Division</label>
            <select id="division" name="division" class="col">
                {division_options}
            </select>
        </div>

        <div class="form-field">
            <label for="with_power">Power</label>
            <select id="with_power" name="with_power" class="col">
                <option value="true" {'selected' if with_power == 'true' else ''}>Performance and Power</option>
                <option value="false" {'selected' if with_power == 'false' else ''}>Performance</option>
            </select>
        </div>

        <div class="form-field">
            <button type="submit" name="submit" value="1" id="results_tablesorter">Submit</button>
        </div>
    </form>
    """

    return html_form

availabilities = ["Available", "Preview", "RDI" ]
#availabilities = ["Available" ]
division=os.environ.get("default_division", "closed")
category=os.environ.get("default_category", "datacenter")

html = ""
for availability in availabilities:
    val = availability.lower()
    html_table = construct_table(category, division, val)

    if html_table:
        html += f"""
        <h2 id="results_heading_{availability.lower()}" class="results_table_heading">{categories[category]} Category: {availability} submissions in {divisions[division]} division</h2>
{tableposhtml}
{html_table}
{tableposhtml}
<hr>
"""
summary = construct_summary_table(category, division)
#print(summary)
html += f"""
<h2 id="count_heading">Count of Results </h2>
{summary}
<hr>
"""

html += """
    <div id="submittervssubmissionchartContainer" class="bgtext" style="height:370px; width:80%; margin:auto;"></div>
    <div id="modelvssubmissionchartContainer" class="bgtext" style="height:370px; width:80%; margin:auto;"></div>
    """

html += generate_html_form(categories, divisions, category, division)


extra_scripts = """
<script type="text/javascript">
var sortcolumnindex = 6, perfsortorder = 1;
$('#submittervssubmissionchartContainer').hide();
$('#modelvssubmissionchartContainer').hide();
</script>

<script type="text/javascript" src="javascripts/init_tablesorter.js"></script>
<script type="text/javascript" src="javascripts/results_tablesorter.js"></script>
<script type="text/javascript" src="javascripts/chart_results.js"></script>
"""

out_html = f"""---
hide:
  - navigation
  - toc
---

<html>
{html}
{extra_scripts}
</html>
"""
with open(os.path.join("docs", "index.md"), "w") as f:
    f.write(out_html)


#print(data)


