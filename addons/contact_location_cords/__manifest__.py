{
    "name": "Contact Location Cords",
    "version": "1.0",
    "depends": [
        "contacts",
        "base_geolocalize",    # provides geo_find()
        "rotary_project_map",  # reuses club_latitude/club_longitude fields
    ],
    "data": ["views/res_partner_location_page.xml"],
    "installable": True,
}
