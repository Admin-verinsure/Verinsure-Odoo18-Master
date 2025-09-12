{
    "name": "Contact Location Cords",
    "version": "1.0",
    "depends": [
        "contacts",
        "base_geolocalize",    # provides partner_latitude/partner_longitude & geo utils
        "rotary_project_map",  # keep if you rely on club_latitude/club_longitude
    ],
    "data": [
        "views/res_partner_location_page.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "contact_location_cords/static/src/js/auto_geocode.js",
        ],
    },
    "installable": True,
}
