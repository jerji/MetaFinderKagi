import requests
from bs4 import BeautifulSoup
from random import randint
import json
import os
from metafinder.utils.agent import user_agent
from metafinder.utils.exception import KagiTokenInvalid
import urllib3
urllib3.disable_warnings()

def find_by_tag(event_list, tag):
    if not isinstance(event_list, list):
        return None
    for item in event_list:
        if isinstance(item, dict) and item.get('tag') == tag:
            return item.get('payload')
    return None

def parse_kagi_sse(text):
    events = {}
    current_event = {}
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('id:'):
            # Save previous event if complete
            if current_event and 'id' in current_event:
                events[current_event['id']] = current_event.get('data')
            # Start new event
            current_event = {'id': line[3:].strip()}
        elif line.startswith('data:'):
            data_content = line[5:].strip()
            # Accumulate multi-line data until next field
            i += 1
            while i < len(lines) and not lines[i].startswith(('id:', 'event:', 'data:')):
                if lines[i].strip(): # Preserve non-empty continuation lines
                    data_content += lines[i]
                i += 1
            i -= 1 # Back up since outer loop increments
            # Parse JSON content
            if data_content:
                try:
                    current_event['data'] = json.loads(data_content)
                except json.JSONDecodeError:
                    current_event['data'] = data_content
        i += 1
    # Don't forget the last event
    if current_event and 'id' in current_event:
        events[current_event['id']] = current_event.get('data')
    return events

def search(target, total, token=None):
    documents = []
    session = requests.Session()

    # determine token (param -> env)
    token = token or os.environ.get('KAGI_TOKEN')
    if not token:
        raise ValueError('Kagi token not provided')

    # login
    session.get(f"https://kagi.com/search?token={token}",
                headers={'User-agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0'},
                timeout=5,
                verify=False,
                allow_redirects=True)

    iterations = 1
    while len(documents) < total and iterations < 10:
        try:
            url_base = f"https://kagi.com/socket/search?q=(filetype:pdf OR filetype:doc OR filetype:docx OR filetype:xls OR filetype:xlsx OR filetype:ppt OR filetype:pptx)+(site:*.{target} OR site:{target})&num={iterations}"


            #results
            response = session.get(url_base,
                                   headers={"User-Agent": user_agent.get(randint(0, len(user_agent)-1))["User-agent"]},
                                   timeout=5,
                                   verify=False,
                                   allow_redirects=True)

            text = response.text
            events = parse_kagi_sse(text)

            if find_by_tag(events.get('0'), 'bang') == '/signin':
                raise KagiTokenInvalid()

            error_payload = find_by_tag(events.get('1'), 'error')
            if isinstance(error_payload, dict) and error_payload.get('type') == 'no_results':
                return documents

            search_payload = find_by_tag(events.get('1'), 'search')
            if not isinstance(search_payload, dict):
                iterations += 1
                continue

            search_results = search_payload.get('content', '')

            soup = BeautifulSoup(search_results, "html.parser")

            all_links = soup.find_all("a")
            for link in all_links:
                href = link.get("href", None)
                if href and target in href and not href.startswith("/") and not href.startswith("https://web.archive.org/"):
                    if href not in documents:
                        documents.append(href)

        except Exception as ex:
            raise ex #It's left over... but it stays there

        iterations += 1

    return documents
