"""
Automated scraper for HK Primary Care Directory
https://apps.pcdirectory.gov.hk/Public/EN/SearchResult

Runs via GitHub Actions to update doctors.csv automatically
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import csv
import re
import time
import os

# Region button IDs on the page
REGION_BUTTONS = ["CommandHK", "CommandKLN", "CommandNT"]

def setup_driver():
    """Setup Chrome WebDriver for headless operation"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def scrape_region(driver, region_id, base_url, max_retries=3):
    """Scrape a single region with retry logic, handling pagination"""
    for attempt in range(max_retries):
        try:
            driver.get(base_url)
            time.sleep(3)

            WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, region_id))
            )

            region_btn = driver.find_element(By.ID, region_id)
            driver.execute_script("arguments[0].click();", region_btn)

            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr .PHName"))
            )
            time.sleep(2)

            all_pages_html = []
            page_num = 1

            while True:
                results_table = driver.find_element(By.CSS_SELECTOR, "tbody")
                html = results_table.get_attribute('outerHTML')
                all_pages_html.append(html)
                print(f"    Page {page_num} scraped")

                try:
                    next_btn = driver.find_element(By.CSS_SELECTOR,
                        ".pagination .PagedList-skipToNext a"
                    )
                    driver.execute_script("arguments[0].click();", next_btn)
                    page_num += 1
                    time.sleep(2)
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr .PHName"))
                    )
                except:
                    break

            return "\n".join(all_pages_html)

        except Exception as e:
            print(f"  Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                print(f"  Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print(f"  All retries exhausted for {region_id}")
                return None

def scrape_all_regions():
    """Scrape doctor data from all regions"""
    driver = setup_driver()
    all_html_parts = []

    base_url = "https://apps.pcdirectory.gov.hk/Public/EN/ServiceTypeAdvancedSearch?ProfID=RMP&ServiceType=TaiPoService"

    try:
        for region_id in REGION_BUTTONS:
            print(f"Scraping region: {region_id}...")
            html = scrape_region(driver, region_id, base_url)
            if html:
                all_html_parts.append(html)
                print(f"  Got {len(html)} characters from {region_id}")
            else:
                print(f"  Failed to scrape {region_id}")
    finally:
        driver.quit()

    return "\n".join(all_html_parts)

def parse_html_to_data(html_content):
    """Parse the scraped HTML into structured data"""
    soup = BeautifulSoup(html_content, 'html.parser')
    data_list = []

    rows = soup.find_all('tr')

    for row in rows:
        name_div = row.find('div', class_='PHName')
        if not name_div:
            continue
        name = name_div.get_text(strip=True)

        phone_link = row.find('a', href=lambda x: x and x.startswith('tel:'))
        phone = phone_link.get_text(strip=True) if phone_link else ""

        practice = ""
        cols = row.find_all('td')
        if len(cols) > 1:
            practice_span = cols[1].find('span')
            if practice_span:
                practice = practice_span.get_text(strip=True)

        address = ""
        lat = ""
        lon = ""

        map_link = row.find('a', href=lambda x: x and 'map.gov.hk' in x)

        if map_link:
            href = map_link.get('href', '')
            match = re.search(r'wgs84/([\d\.]+)/([\d\.]+)', href)
            if match:
                lat = match.group(1)
                lon = match.group(2)

            addr_div = map_link.find('div', class_='SPListTableTd')
            if addr_div:
                address = addr_div.get_text(strip=True)

        if not address and len(cols) > 1:
            addr_divs = cols[1].find_all('div', class_='SPListTableTd')
            for div in addr_divs:
                text = div.get_text(strip=True)
                if text and "Show Map" not in text:
                    address = text
                    break

        address = " ".join(address.split())

        programs = []
        plan_list = row.find('div', class_='plan-list')
        if plan_list:
            program_divs = plan_list.find_all('div', class_='plan')
            for prog in program_divs:
                img = prog.find('img')
                if img and img.get('alt'):
                    programs.append(img.get('alt'))

        if name and address:
            data_list.append({
                'Name': name,
                'Description': practice,
                'Address': address,
                'Phone': phone,
                'Lat': lat,
                'Lon': lon,
                'Programs': "; ".join(programs)
            })

    return data_list

def save_to_csv(data_list, output_filename="doctors.csv"):
    """Save data to CSV file"""
    if not data_list:
        print("No data to save")
        return

    fieldnames = ['Name', 'Description', 'Address', 'Phone', 'Lat', 'Lon', 'Programs']

    with open(output_filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data_list)

    print(f"Saved {len(data_list)} records to {output_filename}")

def main():
    print("Starting HK Primary Care Directory scraper...")
    print("=" * 50)

    html_content = scrape_all_regions()

    if not html_content:
        print("No data scraped!")
        return

    print("\nParsing scraped data...")
    data_list = parse_html_to_data(html_content)
    print(f"Parsed {len(data_list)} doctor records")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_file = os.path.join(script_dir, "doctors.csv")
    save_to_csv(data_list, csv_file)

    print("\nDone!")

if __name__ == "__main__":
    main()
