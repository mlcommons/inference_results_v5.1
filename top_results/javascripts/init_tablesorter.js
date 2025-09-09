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


function tableSorterInit() {
    $(".tablesorter").each(function() {
        var $table = $(this);
        var containerId = $table.closest('div').attr('id');

        // Define the sort column index and the sort order (asc/desc)
        var sortColumnIndex = 0; // Change this value to the desired column index for initial sorting
        var sortOrder = 0; // Change to 1 for descending order

        // Initialize the tablesorter
        $table.tablesorter({
            // *** APPEARANCE ***
            theme: 'blue', // Apply the theme to the table

            widthFixed: false, // Don't fix column widths
            showProcessing: false, // Don't show a processing indicator while sorting
            headerTemplate: '{content}', // Template for header content

            onRenderHeader: function(index) {
                $(this).find('div.tablesorter-header-inner').addClass('roundedCorners');
            },

            // *** FUNCTIONALITY ***
            cancelSelection: true, // Prevent text selection in the header
            dateFormat: "mmddyyyy", // Date format used for sorting
            sortMultiSortKey: "shiftKey", // Multi-sort using the shift key
            sortResetKey: 'ctrlKey', // Reset sort with the control key
            usNumberFormat: true, // Use US number format (e.g., 1,000.00)
            delayInit: false, // Don't delay initialization
            serverSideSorting: false, // Client-side sorting by default

            // *** SORT OPTIONS ***
            headers: {
                0: { sorter: "text" }, // Set column 0 to text sorting
                1: { sorter: "text" }, // Set column 1 to text sorting
                3: { sorter: "digit" } // Set column 3 to numeric sorting
            },

            ignoreCase: true, // Ignore case when sorting
            sortList: [
                [sortColumnIndex, sortOrder], // Initial sort settings
                [1, 0], // Sort by column 1 in ascending order
                [2, 0], // Sort by column 2 in ascending order
                [3, 0]  // Sort by column 3 in ascending order
            ],
            sortInitialOrder: "asc", // Initial sort direction
            sortLocaleCompare: false, // Do not use locale compare for sorting
            sortReset: false, // Reset sort on third click
            sortRestart: false, // Don't restart sort on clicking unsorted columns
            emptyTo: "bottom", // Empty cells go to the bottom
            stringTo: "max", // Sort strings in numeric columns as max
            textExtraction: {
                0: function(node) {
                    return $(node).text();
                },
                1: function(node) {
                    return $(node).text();
                }
            },

            // *** WIDGETS ***
            initWidgets: true,
            widgets: ['zebra', 'columns'], // Enable zebra stripes and columns widget

            widgetOptions: {
                zebra: [
                    "ui-widget-content even",
                    "ui-state-default odd"
                ],
                uitheme: 'jui', // Set jQuery UI theme
                columns: ["primary", "secondary", "tertiary"],
                columns_tfoot: true,
                columns_thead: true,
                filter_childRows: false,
                filter_columnFilters: true,
                filter_cssFilter: "tablesorter-filter",
                filter_hideFilters: false,
                filter_ignoreCase: true,
                filter_reset: null,
                filter_searchDelay: 300,
                filter_serversideFiltering: false,
                filter_startsWith: false,
                filter_useParsedData: false,
                resizable: true,
                saveSort: true,
                stickyHeaders: "tablesorter-stickyHeader"
            },

            // *** CALLBACKS ***
            initialized: function(table) {},

            // *** CSS CLASS NAMES ***
            tableClass: 'tablesorter',
            cssAsc: "tablesorter-headerSortUp",
            cssDesc: "tablesorter-headerSortDown",
            cssHeader: "tablesorter-header",
            cssHeaderRow: "tablesorter-headerRow",
            cssIcon: "tablesorter-icon",
            cssChildRow: "tablesorter-childRow",
            cssInfoBlock: "tablesorter-infoOnly",
            cssProcessing: "tablesorter-processing",

            // *** SELECTORS ***
            selectorHeaders: '> thead th, > thead td',
            selectorSort: "th, td",
            selectorRemove: "tr.remove-me",

            // *** DEBUGGING ***
            debug: false
        }).tablesorterPager({
            container: $("#" + containerId + " .pager"),
            ajaxUrl: null,
            ajaxProcessing: function(ajax) {
                if (ajax && ajax.hasOwnProperty('data')) {
                    return [ajax.data, ajax.total_rows];
                }
            },
            output: '{startRow} to {endRow} ({totalRows})',
            updateArrows: true,
            page: 0,
            size: 10,
            fixedHeight: true,
            removeRows: false,
            cssNext: '.next',
            cssPrev: '.prev',
            cssFirst: '.first',
            cssLast: '.last',
            cssGoto: '.gotoPage',
            cssPageDisplay: '.pagedisplay',
            cssPageSize: '.pagesize',
            cssDisabled: 'disabled'
        });
    });

    $('table')
        .tablesorter()
        .bind('tablesorter-ready', function(e, table) {
            if (typeof drawCharts === 'function') {
                drawCharts();
            }
        });

    // Extend the themes to change any of the default class names ** NEW **
    $.extend($.tablesorter.themes.jui, {
        table: 'ui-widget ui-widget-content ui-corner-all',
        header: 'ui-widget-header ui-corner-all ui-state-default',
        icons: 'ui-icon',
        sortNone: 'ui-icon-carat-2-n-s',
        sortAsc: 'ui-icon-carat-1-n',
        sortDesc: 'ui-icon-carat-1-s',
        active: 'ui-state-active',
        hover: 'ui-state-hover',
        filterRow: '',
        even: 'ui-widget-content',
        odd: 'ui-state-default'
    });
}
