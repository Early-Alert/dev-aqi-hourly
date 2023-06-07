from datetime import datetime, date, timezone
import logging, requests, json, os, pytz
from arcgis import GIS
from io import BytesIO
import azure.functions as func
from PIL import Image, ImageDraw, ImageFont
from arcgis.mapping import export_map
from azure.storage.blob import BlobServiceClient
from jinja2 import Environment, FileSystemLoader

GIS_USERNAME = "Developer1"
GIS_PASSWORD = "qweRTY77**"
AERIS_ID = 'IJwChrr7utrp6BFWVnJ1A'
AERIS_SECRET = 'WmzZHc1PnJiAsr996tFNwfsPt7IqetRHHuB8Ldty'



def hd_hourly_report():
    client_json_data = aqi_clients()
    for i in range(len(client_json_data)):
        cid = client_json_data[i].get('cid')
        name = client_json_data[i].get('company')
        aqithreshold = client_json_data[i].get('aqithreshold')
        states = client_json_data[i].get('aqistates')
        aqistates = ','.join("'{}'".format(word) for word in states.split(','))
        aqi_email = client_json_data[i].get('aqi_email')
        logging.info(f"{cid}, {name}, {aqithreshold}, {states}, {aqistates}, {aqi_email}")
        products, date, current_time, bool_value = create_report(cid, aqithreshold, aqistates, aqi_email)
        logging.info(f"{products}, {date}, {current_time}, {bool_value}")
        if bool_value:
            logging.info('location entries already exist in the db')
            return ({"success": True})
        else:
            if not products:
                logging.info('No locations with aqi')
                return ({"success": True})
            else:
                map_img = print_hd_map()
                url, pacific_time = create_hd_graphic(map_img)
                logging.info(f"url, pacific_time {url} {pacific_time}")
                context = {"name":name, "aqithreshold": aqithreshold, "products": products, "date": date, "current_time":pacific_time, "url": url}
                # response = render(request, "hdAqiHourly/hd.html", context)
                
                script_dir = os.path.dirname(os.path.abspath(__file__))
                # logging.info(f"script_dir {script_dir}")
                templates_dir = os.path.join(script_dir, 'templates')
                # logging.info(f"templates_dir {templates_dir}")
                env = Environment(loader=FileSystemLoader(templates_dir))
                # logging.info(f"env {env}")
                template = env.get_template('report.html')
                # logging.info(f"template {template}")
                rendered_template = template.render(data=context)
                # logging.info(f"rendered_template {rendered_template}")
                
                output_path = os.path.join(script_dir, 'output.html')
                # logging.info(f"output_path {output_path}")
                with open(os.path.join("/tmp", "output.html"), 'w') as file:
                # with open(output_path, 'w') as file:
                    file.write(rendered_template)

                send_aqi_email(name, aqi_email, context)
                # send_loc_emails(products, context)
                logging.info('emails sent with new aqi locations')
                return ({"success": True})


def send_aqi_email(name, aqi_email, context):
    url = "https://api.mailgun.net/v3/earlyalert.com/messages"
    with open(os.path.join("/tmp", "output.html"), "r") as file:
        html_content = file.read()
    response = requests.post(
        url,
        auth=("api", "key-abc3ac7030c2113b91c27b6733ebe510"),
        data={
            "from": "airquality@earlyalert.com",
            "to": "ykhan@earlyalert.com",
            "subject": "DEV - HD-Hourly AQI",
            "html": html_content
        }
    )
    return response.text

def create_report(cid, aqithreshold, aqistates, aqi_email):
    print("create_report")
    bool = True
    today = date.today()
    d2 = today.strftime("%B %d, %Y")
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    products = []
    gis = GIS("https://maps.earlyalert.com/portal/home/", GIS_USERNAME,
              GIS_PASSWORD)
    item = gis.content.get("3604f01a15274e139e47ba1fe00183aa")
    feature_layer = item.layers[0]
    query = 'ClientId = {} AND State IN ({})'.format(cid, aqistates)
    f = feature_layer.query(where=query)
    for i in range(len(f.features)):
    # for i in range(5):
        lat = f.features[i].attributes.get('lat')
        lon = f.features[i].attributes.get('lon')
        if isinstance(lat, float) and isinstance(lon, float):
            aqi = observed_aqi(lat, lon)
            if aqi > aqithreshold:
            # if aqi > 20:
                json_output = f.features[i].attributes
                loc_name = json_output.get('name')
                loc_code = json_output.get('code')
                loc_city = json_output.get('city')
                loc_state = json_output.get('state')
                """These Lines Are Commented Out For Dev Instance"""
                # if cid == 35:
                #     bool = check_insert(loc_name, now.day)
                #     if bool:
                #         print(bool)
                #     else:    
                #         insert_loc_db(loc_name, cid, loc_code, loc_city, loc_state, aqi)
                bool = False
                json_output['aqi'] = aqi
                products.append(json_output)
    return products, d2, current_time, bool

def print_hd_map():
        """
        Using the base map_json.json file, print the HD airquality map. Map contains observed air
        quality contours with HD dots overlaid. Download the map and save it to blob.
        """
        gis = GIS(
            "https://maps.earlyalert.com/portal/home/", GIS_USERNAME, GIS_PASSWORD
        )

        generic_gis = GIS("https://www.arcgis.com")
        generic_token = generic_gis._con.token

        token = gis._con.token

        with open("map_json.json") as f:
            data = json.load(f)

        # update token
        for layer in data["operationalLayers"]:
            if "token" in layer:
                if layer["id"] in ["VectorTile_4381", "VectorTile_8450"]:
                    layer["token"] = generic_token
                else:
                    layer["token"] = token

        map_file = export_map(web_map_as_json=json.dumps(data), format="PNG32")
        print(map_file)
        issue_date = datetime.now(timezone.utc).astimezone()
        time = issue_date.strftime("%Y-%m-%d-%H-%M-%S")
        download_folder = os.path.join("/tmp", "hd_map{}".format(time))
        map_file.download(download_folder)

        png_files = [f for f in os.listdir(download_folder) if f.endswith(".png")]
        png_file = png_files[0]
        return Image.open(os.path.join(download_folder, png_file))

def create_hd_graphic(map_img):
    """
    Combines the base template, legend and map image into 1 graphic. Also adds title that
    corresponds to date in Pacific Time. Uploads file to blob.
    """
    download_folder = ("/tmp")
    template = download_template_graphic("hd template")
    legend = download_template_graphic("legend")
    

    # resize map
    basewidth = 725
    wpercent = basewidth / float(map_img.size[0])
    hsize = int((float(map_img.size[1]) * float(wpercent)))
    map_img = map_img.resize((basewidth, hsize), Image.ANTIALIAS)

    # paste map
    x, y = template.size
    template.paste(map_img, (30, 150))

    # paste legend
    # x, y = legend.size
    template.paste(legend, (45, 230))
    # issue_date = timezone.now()
    issue_date = datetime.now(timezone.utc).astimezone()
    d = ImageDraw.Draw(template)
    
    
    # pac_time = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo.localtime(issue_date, pytz.timezone("US/Pacific"))
    # Get the current date and time in UTC
    now_utc = datetime.now(timezone.utc)

    # Convert the UTC date and time to the "US/Pacific" time zone
    pacific_tz = pytz.timezone("US/Pacific")
    pac_time = now_utc.astimezone(pacific_tz)
    
    pacific_time = f"{pac_time:%m/%d/%y %H:%M %p}"
    text = f"Observed Air Quality as of {pac_time:%m/%d/%y %H:%M %p} PT"
    time = issue_date.strftime("%Y-%m-%d")
    # font = ImageFont.truetype("fonts/CALIBRIB.TTF", 18)
    d.text((35, 120), text, fill=(255, 255, 0))

    basewidth = 800
    wpercent = basewidth / float(template.size[0])
    hsize = int((float(template.size[1]) * float(wpercent)))
    template_rz = template.resize((basewidth, hsize), Image.ANTIALIAS)

    # file_path = os.path.join(download_folder, "combined.png")
    # template_rz.save("combined.png", "PNG")

    file_path = os.path.join(download_folder, "combined.png")
    template_rz.save(file_path, "PNG")

    blob_service = BlobServiceClient(account_url="https://eapytoolsstorage.blob.core.windows.net/", credential= "lOj9oe2csu0p7Mxky7rdZOMlTLYqLA0pRPZNSU+4Ux93Ph1ui76kyDngxrNS1qv3FhT1t+MTP3oFwnJ8PMV7Xw==")
    blob_client = blob_service.get_blob_client(container="eapytoools-static", blob= "comcast_aq/maps/hd_slide{}.png".format(time))
    if blob_client.exists():
        blob_client.delete_blob()
    else:
        print("The blob doesn't exist")
    with open("combined.png", "rb") as the_file:
        blob_client.upload_blob(the_file)
    url = "https://eapytoolsstorage.blob.core.windows.net/eapytoools-static/comcast_aq/maps/hd_slide{}.png".format(time)
    return url, pacific_time

def observed_aqi(lat, lon):
    endpoint_url = "https://api.aerisapi.com/airquality/{},{}"
    forecast_r = requests.get(
        endpoint_url.format(lat, lon),
        params={
            "client_id": AERIS_ID,
            "client_secret": AERIS_SECRET
        },
    )
    response = forecast_r.json()
    if response["success"]:
        data = response["response"][0]
        period = data["periods"][0]
        for pollutant in period["pollutants"]:
            if pollutant["type"] == "pm2.5":
                if not isinstance(pollutant["aqi"], int):
                    return 0
                else:
                    return pollutant["aqi"]
            else: continue
    else: return 0

def generate_esri_token():  

    url = "https://www.arcgis.com/sharing/generateToken"
    params = {
        "f": "json",
        "username": 'EA_Developer1',
        "password": GIS_PASSWORD,
        "client": "referer",
        "referer": "https://maps.earlyalert.com/portal/home/"
    }
    r = requests.post(url, data=params)
    token = r.json()["token"]
    return token

def aqi_clients():
    aq_cid_list = []
    url = 'https://services8.arcgis.com/lrWk3ELQFeb23nh1/arcgis/rest/services/service_d8f8bb17c9274da9940c1daaeedb833a/FeatureServer/0/query?'
    token = generate_esri_token()
    params = {
        'where': "cid=35",
        'geometryType': 'esriGeometryEnvelope',
        'spatialRel': 'esriSpatialRelIntersects',
        'relationParam': '',
        'outFields': '*',
        'returnGeometry': 'true',
        'geometryPrecision': '',
        'outSR': '',
        'returnIdsOnly': 'false',
        'returnCountOnly': 'false',
        'orderByFields': '',
        'groupByFieldsForStatistics': '',
        'returnZ': 'false',
        'returnM': 'false',
        'returnDistinctValues': 'false',
        'f': 'pjson',
        'token': token
    }
    r = requests.get(url, params=params)
    output_data = r.json()
    length = len(output_data.get('features'))
    for i in range(length):
        data = output_data.get('features')[i].get('attributes')
        aq_cid_list.append(data)
    return aq_cid_list

def download_template_graphic(filename):
    """
    Download image file from blob. Return PIL image object.
    """
    blob_service = BlobServiceClient(account_url="https://eapytoolsstorage.blob.core.windows.net/", credential= "lOj9oe2csu0p7Mxky7rdZOMlTLYqLA0pRPZNSU+4Ux93Ph1ui76kyDngxrNS1qv3FhT1t+MTP3oFwnJ8PMV7Xw==")
    blob_client = blob_service.get_blob_client(container="eapytoools-static", blob= "comcast_aq/maps/{}.png".format(filename))
    template = Image.open(BytesIO(blob_client.download_blob().content_as_bytes()))
    return template


def main(mytimer: func.TimerRequest) -> None:
    utc_timestamp = datetime.utcnow().replace(
        tzinfo=timezone.utc).isoformat()

    if mytimer.past_due:
        logging.info('The timer is past due!')
    logging.info(GIS)
    logging.info(Image)
    logging.info(BlobServiceClient)
    hd_hourly_report()
    logging.info('Python timer trigger function ran at %s', utc_timestamp)

# def maain():
#     utc_timestamp = datetime.utcnow().replace(
#         tzinfo=timezone.utc).isoformat()
#     hd_hourly_report()
#     logging.info('Python timer trigger function ran at %s', utc_timestamp)

# maain()
