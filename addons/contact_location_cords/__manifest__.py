{
    "name": "Contact Location Coordinates",
    "version": "1.0",
    "depends": [
        "contacts",
        "base_geolocalize",   # for geo_find()
        "rotary_project_map", # reuse club_latitude/club_longitude fields
    ],
    "data": ["views/res_partner_location_page.xml"],
    "installable": True,
}
