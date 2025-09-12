# contact_location_cords/__manifest__.py
{
    "name": "Contact Location Cords",
    "version": "1.0",
    "depends": [
        "contacts",
        "base_geolocalize",
        "rotary_project_map",
    ],
    "data": ["views/res_partner_location_page.xml"],
    "assets": {
        "web.assets_backend": [
            "contact_location_cords/static/src/js/auto_geocode.js",
        ],
    },
    "installable": True,
}
