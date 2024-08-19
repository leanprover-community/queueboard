#!/usr/bin/env python3

# This script accepts json files as command line arguments and displays the data in an HTML dashboard

import sys
import json
from datetime import datetime, UTC
from dateutil import relativedelta
from enum import Enum, unique

@unique
class PRList(Enum):
    '''The different kind of PR lists this dashboard creates'''
    Queue = 0
    StaleReadyToMerge = 1
    StaleMaintainerMerge = 2
    StaleDelegated = 3
    StaleNewContributor = 4
    Unlabelled = 5

# All input files this script expects. Needs to be kept in sync with dashboard.sh,
# but this script will complain if something unexpected happens.
EXPECTED_INPUT_FILES = {
    "queue.json" : PRList.Queue,
    "ready-to-merge.json" : PRList.StaleReadyToMerge,
    "maintainer-merge.json" : PRList.StaleMaintainerMerge,
    "delegated.json" : PRList.StaleDelegated,
    "new-contributor.json" : PRList.StaleNewContributor,
    "unlabelled.json" : PRList.Unlabelled,
}

def main():
    # Check if the user has provided the correct number of arguments
    if len(sys.argv) < 3:
        print("Usage: python3 dashboard.py <pr-info.json> <json_file1> <json_file2> ...")
        sys.exit(1)

    print_html5_header()

    # Iterate over the json files provided by the user.
    dataFilesWithKind = []
    for i in range(2, len(sys.argv)):
        filename = sys.argv[i]
        if filename not in EXPECTED_INPUT_FILES:
            print(f"bad argument: file {filename} is not recognised; did you mean one of these: {EXPECTED_INPUT_FILES.keys()}?")
            sys.exit(1)
        with open(filename) as f:
            data = json.load(f)
            dataFilesWithKind.append(data, EXPECTED_INPUT_FILES[filename])

    # Process all data files for the same PR list together.
    for kind in PRList.__members__:
        files = [k for (d, k) in dataFilesWithKind if k == kind]
        print_dashboard(files, kind)

    print_html5_footer()

def print_html5_header():
    print("""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Mathlib Review Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.5.1/jquery.min.js"
			integrity="sha512-bLT0Qm9VnAYZDflyKcBaQ2gg0hSYNQrJ8RilYldYQ1FxQYoCLtUjuuRuZo+fjqhx/qtq/1itJ0C2ejDxltZVFg=="
			crossorigin="anonymous"></script>
    <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.10.22/css/jquery.dataTables.css">
    <script type="text/javascript" charset="utf8" src="https://cdn.datatables.net/1.10.22/js/jquery.dataTables.js"></script>
    <link rel='stylesheet' href='style.css'>
    <base target="_blank">
    </head>
    <body>
    <h1>Mathlib Review Dashboard</h1>""")
    # FUTURE: can this time be displayed in the local time zone of the user viewing this page?
    updated = datetime.now(UTC).strftime("%B %d, %Y at %H:%M UTC")
    print(f"<small>This dashboard was last updated on: {updated}</small>")

def print_html5_footer():
    print("""
    <script>
    $(document).ready( function () {
        $('table').DataTable({
                pageLength: 10,
				"searching": false,
        });
    });
    </script>
    </body>
    </html>
    """)

# An HTML link to a mathlib PR from the PR number
def pr_link(number, url):
    return "<a href='{}'>#{}</a>".format(url, number)

# An HTML link to a GitHub user profile
def user_link(author):
    login = author["login"]
    url   = author["url"]
    return "<a href='{}'>{}</a>".format(url, login)

# An HTML link to a mathlib PR from the PR title
def title_link(title, url):
    return "<a href='{}'>{}</a>".format(url, title)

# An HTML link to a Github label in the mathlib repo
def label_link(label):

    # Function to check if the colour of the label is light or dark
    # adapted from https://codepen.io/WebSeed/pen/pvgqEq
    def isLight(r, g, b):
        # Counting the perceptive luminance
        # human eye favors green color...
        a = 1 - (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return (a < 0.5)

    name  = label["name"]
    url   = label["url"]
    bgcolor = label["color"]
    fgcolor = "000000" if isLight(int(bgcolor[:2], 16), int(bgcolor[2:4], 16), int(bgcolor[4:], 16)) else "FFFFFF"
    s  = "<a href='{}'>".format(url)
    s += "<span class='label' style='color: #{}; background: #{}'>".format(fgcolor, bgcolor)
    s += "{}".format(name)
    s += "</span>"
    s += "</a>"
    return s

# Function to format the time of the last update
# Input is in the format: "2020-11-02T14:23:56Z"
# Output is in the format: "2020-11-02 14:23 (2 days ago)"
def time_info(updatedAt):
    updated = datetime.strptime(updatedAt, "%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now()

    # Calculate the difference in time
    delta = relativedelta.relativedelta(now, updated)

    # Format the output
    s = updated.strftime("%Y-%m-%d %H:%M")
    if delta.years > 0:
        s += " ({} years ago)".format(delta.years)
    elif delta.months > 0:
        s += " ({} months ago)".format(delta.months)
    elif delta.days > 0:
        s += " ({} days ago)".format(delta.days)
    elif delta.hours > 0:
        s += " ({} hours ago)".format(delta.hours)
    elif delta.minutes > 0:
        s += " ({} minutes ago)".format(delta.minutes)
    else:
        s += " ({} seconds ago)".format(delta.seconds)

    return s

def print_dashboard(datae, kind : PRList):
    '''`datae` is a list of parsed data files to process'''
    # If there are no PRs in any list for this file, skip the table header and print a bold notice
    # such as "There are currently **no**** stale `delegated` PRs. Congratulations!".
    if all(datae, lambda data : not data["output"][0]["data"]["search"]["nodes"]):
        description = {
            PRList.Queue : "PRs on the review queue",
            PRList.StaleMaintainerMerge : "stale PRs labelled maintainer merge",
            PRList.StaleDelegated : "stale delegated PRs",
            PRList.StaleReadyToMerge : "stale PRs labelled ready-to-merge",
            PRList.StaleNewContributor : "stale PRs by new contributors",
            PRList.Unlabelled : "unlabelled PRs",
        }
        print("<h1 id=\"{}\">{}</h1>".format(data["id"], data["title"]))
        print(f'There are currently <b>no</b> {description[kind]}. Congratulations!\n')
        return

    # Explain what each PR list contains.
    notupdated = "which have not been updated in the past"
    explanation = {
        PRList.Queue : "All PRs which are ready for review: CI passes, no merge conflict and not blocked on other PRs",
        PRList.Unlabelled : "PRs without a 't-something' label which are not labelled 'CI'",
        PRList.StaleDelegated : f"PRs labelled 'delegated' {notupdated} 24 hours",
        PRList.StaleReadyToMerge : f"PRs labelled 'ready-to-merge' {notupdated} 24 hours",
        PRList.StaleMaintainerMerge : f"PRs labelled 'maintainer-merge' but not 'ready-to-merge' {notupdated} 24 hours",
        PRList.StaleNewContributor : f"PR labelled 'new-contributor' {notupdated} 7 days",
    }[kind]
    # Use a header to make space before the table, but don't make it bold.
    explanation = f'<h5 style="font-weight:normal">{explanation}</h5>\n'
    # Title of each list, and the corresponding HTML anchor.
    (id, title) = {
        PRList.Queue : ("queue", "Queue"),
        PRList.Unlabelled : ("unlabelled", "PRs without an area label"),
        PRList.StaleDelegated : ("stale-delegated", "Stale delegated"),
        PRList.StaleNewContributor : ("stale-new-contributor", "Stale new contributor"),
        PRList.StaleMaintainerMerge : ("stale-maintainer-merge", "Stale maintainer-merge"),
        PRList.StaleReadyToMerge : ("stale-ready-to-merge", "Stale ready-to-merge")
    }
    print(f"""<h1 id=\"{id}\">{title}</h1>
    {explanation}
    <table>
    <thead>
    <tr>
    <th>Number</th>
    <th>Author</th>
    <th>Title</th>
    <th>Labels</th>
    <th>+/-</th>
    <th>&#128221;</th>
    <th>&#128172;</th>
    <th>Updated</th>
    </tr>
    </thead>""")

    # Open the file containing the PR info
    with open(sys.argv[1], 'r') as f:
        pr_infos = json.load(f)

        # Iterate over each data file and print each entry in a row.
        for data in datae:
            for page in data["output"]:
                for entry in page["data"]["search"]["nodes"]:
                    print("<tr>")
                    print("<td>{}</td>".format(pr_link(entry["number"], entry["url"])))
                    print("<td>{}</td>".format(user_link(entry["author"])))
                    print("<td>{}</td>".format(title_link(entry["title"], entry["url"])))
                    print("<td>")
                    for label in entry["labels"]["nodes"]:
                        print(label_link(label))
                    print("</td>")

                    try:
                        pr_info = pr_infos[str(entry["number"])]
                        print("<td>{}/{}</td>".format(pr_info["additions"], pr_info["deletions"]))
                        print("<td>{}</td>".format(pr_info["changed_files"]))
                        comments = pr_info["comments"] + pr_info["review_comments"]
                        print("<td>{}</td>".format(comments))
                    except KeyError:
                        pr_info = {"additions": -1, "deletions": -1, "changed_files": -1, "comments": -1, "review_comments": -1}
                        print("<td>{}/{}</td>".format(pr_info["additions"], pr_info["deletions"]))
                        print("<td>{}</td>".format(pr_info["changed_files"]))
                        comments = pr_info["comments"] + pr_info["review_comments"]
                        print("<td>{}</td>".format(comments))
                        print("PR #{} is wicked!".format(entry["number"]), file=sys.stderr)

                    print("<td>{}</td>".format(time_info(entry["updatedAt"])))
                    print("</tr>")

    # Print the footer
    print("</table>")

main()
