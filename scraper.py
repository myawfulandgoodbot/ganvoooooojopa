import re
from urllib import parse
from bs4 import BeautifulSoup
import requests

YAHUOKU_SEARCH_TEMPLATE = "https://auctions.yahoo.co.jp/search/search?p={query}&b={start}&n={count}&s1=new&o1=d"

POST_TIMESTAMP_REGEX = r"^.*i-img\d+x\d+-(\d{10}).*$"
AUCTION_TIMESTAMP_REGEX = r"^.*etm=(\d{10}),stm=(\d{10}).*$"

def get_raw_results(query: str, count: int = 100):
    url = YAHUOKU_SEARCH_TEMPLATE.format(query=parse.quote_plus(query), start=1, count=count)
    print(f"[GET] {url}")
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.text

def parse_raw_results(raw: str):
    results = []
    soup = BeautifulSoup(raw, "lxml")
    product_details = soup.find_all("div", class_="Product__detail")
    for product_detail in product_details:
        product_bonuses = product_detail.find_all("div", class_="Product__bonus")
        product_titlelinks = product_detail.find_all("a", class_="Product__titleLink")
        if not product_bonuses or not product_titlelinks:
            continue
        product_bonus = product_bonuses[0]
        product_titlelink = product_titlelinks[0]

        auction_title = product_titlelink.get("data-auction-title")
        auction_img = product_titlelink.get("data-auction-img")
        href = product_titlelink.get("href")
        cl_params = product_titlelink.get("data-cl-params")

        if not all([auction_title, auction_img, href, cl_params]):
            continue

        match = re.match(POST_TIMESTAMP_REGEX, auction_img)
        if not match:
            continue
        post_timestamp = int(match.group(1))

        match = re.match(AUCTION_TIMESTAMP_REGEX, cl_params)
        if not match:
            continue
        end_timestamp = int(match.group(1))
        start_timestamp = int(match.group(2))

        auction_id = product_bonus.get("data-auction-id")
        auction_buynowprice = product_bonus.get("data-auction-buynowprice")
        auction_price = product_bonus.get("data-auction-price")
        auction_startprice = product_bonus.get("data-auction-startprice")

        result = {
            "title": auction_title,
            "img": auction_img,
            "url": href,
            "post_ts": post_timestamp,
            "end_ts": end_timestamp,
            "start_ts": start_timestamp,
            "item_id": auction_id,
            "buynow_price": auction_buynowprice,
            "curr_price": auction_price,
            "start_price": auction_startprice,
        }
        results.append(result)
    return results

def search(query: str, count: int = 100):
    raw = get_raw_results(query, count)
    return parse_raw_results(raw)