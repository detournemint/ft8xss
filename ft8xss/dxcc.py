"""Callsign prefix -> DXCC entity.

Not a complete DXCC implementation (that needs the full ARRL prefix/exception
list); this covers the entities an HF FT8 station actually hears, matching
longest-prefix-first. Good enough to answer "is this a new one for me?".
"""
import re

# longest prefixes first within each group; lookup sorts by length anyway
PREFIXES = {
    # North America
    "K": "United States", "W": "United States", "N": "United States",
    "AA": "United States", "AB": "United States", "AC": "United States",
    "AD": "United States", "AE": "United States", "AF": "United States",
    "AG": "United States", "AI": "United States", "AJ": "United States",
    "AK": "United States", "AL": "Alaska", "KL": "Alaska", "NL": "Alaska",
    "WL": "Alaska", "KH6": "Hawaii", "AH6": "Hawaii", "NH6": "Hawaii",
    "WH6": "Hawaii", "KP4": "Puerto Rico", "NP4": "Puerto Rico",
    "WP4": "Puerto Rico", "KP2": "US Virgin Is", "KG4": "Guantanamo Bay",
    "KH2": "Guam", "KH0": "Mariana Is", "KH8": "American Samoa",
    "VE": "Canada", "VA": "Canada", "VO": "Canada", "VY": "Canada",
    "CY0": "Sable Is", "CY9": "St Paul Is",
    "XE": "Mexico", "XF": "Mexico", "XA": "Mexico", "XB": "Mexico",
    "XC": "Mexico", "4A": "Mexico", "6D": "Mexico",
    # Caribbean / Central America
    "CO": "Cuba", "CM": "Cuba", "HI": "Dominican Rep", "HH": "Haiti",
    "6Y": "Jamaica", "ZF": "Cayman Is", "C6": "Bahamas", "VP2E": "Anguilla",
    "VP2M": "Montserrat", "VP2V": "British Virgin Is", "V2": "Antigua",
    "J3": "Grenada", "J6": "St Lucia", "J7": "Dominica", "J8": "St Vincent",
    "8P": "Barbados", "9Y": "Trinidad & Tobago", "PJ2": "Curacao",
    "PJ4": "Bonaire", "PJ7": "Sint Maarten", "FG": "Guadeloupe",
    "FM": "Martinique", "FS": "Saint Martin", "TI": "Costa Rica",
    "TG": "Guatemala", "YS": "El Salvador", "HR": "Honduras",
    "YN": "Nicaragua", "HP": "Panama", "V3": "Belize",
    # South America
    "PY": "Brazil", "PP": "Brazil", "PT": "Brazil", "PU": "Brazil",
    "PR": "Brazil", "PS": "Brazil", "ZZ": "Brazil",
    "LU": "Argentina", "CE": "Chile", "CA": "Chile", "CB": "Chile",
    "CX": "Uruguay", "ZP": "Paraguay", "CP": "Bolivia", "OA": "Peru",
    "HC": "Ecuador", "HK": "Colombia", "YV": "Venezuela", "8R": "Guyana",
    "PZ": "Suriname", "FY": "French Guiana", "VP8": "Falkland Is",
    # Europe
    "G": "England", "M": "England", "2E": "England",
    "GM": "Scotland", "MM": "Scotland", "2M": "Scotland",
    "GW": "Wales", "MW": "Wales", "2W": "Wales",
    "GI": "Northern Ireland", "MI": "Northern Ireland",
    "GD": "Isle of Man", "MD": "Isle of Man", "GU": "Guernsey",
    "MU": "Guernsey", "GJ": "Jersey", "MJ": "Jersey",
    "EI": "Ireland", "EJ": "Ireland",
    "F": "France", "TM": "France", "TK": "Corsica",
    "DL": "Germany", "DA": "Germany", "DB": "Germany", "DC": "Germany",
    "DD": "Germany", "DF": "Germany", "DG": "Germany", "DH": "Germany",
    "DJ": "Germany", "DK": "Germany", "DM": "Germany", "DO": "Germany",
    "DP": "Germany", "DR": "Germany",
    "PA": "Netherlands", "PB": "Netherlands", "PC": "Netherlands",
    "PD": "Netherlands", "PE": "Netherlands", "PF": "Netherlands",
    "PG": "Netherlands", "PH": "Netherlands", "PI": "Netherlands",
    "ON": "Belgium", "OO": "Belgium", "OT": "Belgium",
    "LX": "Luxembourg", "HB0": "Liechtenstein", "HB": "Switzerland",
    "OE": "Austria", "I": "Italy", "IS": "Sardinia", "IT9": "Sicily",
    "EA6": "Balearic Is", "EA8": "Canary Is", "EA9": "Ceuta & Melilla",
    "EA": "Spain", "EB": "Spain", "EC": "Spain", "ED": "Spain",
    "EE": "Spain", "EF": "Spain", "EG": "Spain", "EH": "Spain",
    "CT3": "Madeira", "CT": "Portugal", "CR": "Portugal", "CU": "Azores",
    "SM": "Sweden", "SA": "Sweden", "SB": "Sweden", "SC": "Sweden",
    "SD": "Sweden", "SE": "Sweden", "SF": "Sweden", "SG": "Sweden",
    "LA": "Norway", "LB": "Norway", "LC": "Norway", "LG": "Norway",
    "LJ": "Norway", "LN": "Norway", "JW": "Svalbard", "JX": "Jan Mayen",
    "OH0": "Aland Is", "OJ0": "Market Reef", "OH": "Finland",
    "OF": "Finland", "OG": "Finland", "OI": "Finland",
    "OZ": "Denmark", "OU": "Denmark", "OV": "Denmark", "5P": "Denmark",
    "OX": "Greenland", "OY": "Faroe Is", "TF": "Iceland",
    "SP": "Poland", "SN": "Poland", "SO": "Poland", "SQ": "Poland",
    "SR": "Poland", "3Z": "Poland", "HF": "Poland",
    "OK": "Czech Republic", "OL": "Czech Republic",
    "OM": "Slovakia", "HA": "Hungary", "HG": "Hungary",
    "YO": "Romania", "YP": "Romania", "YQ": "Romania", "YR": "Romania",
    "LZ": "Bulgaria", "SV5": "Dodecanese", "SV9": "Crete", "SV": "Greece",
    "SW": "Greece", "SX": "Greece", "SY": "Greece", "SZ": "Greece",
    "S5": "Slovenia", "9A": "Croatia", "E7": "Bosnia-Herzegovina",
    "YU": "Serbia", "YT": "Serbia", "4O": "Montenegro", "Z3": "North Macedonia",
    "ZA": "Albania", "1A": "Sov Mil Order of Malta", "9H": "Malta",
    "T7": "San Marino", "HV": "Vatican", "3A": "Monaco", "C3": "Andorra",
    "ZB2": "Gibraltar", "ES": "Estonia", "YL": "Latvia", "LY": "Lithuania",
    "EW": "Belarus", "EU": "Belarus", "EV": "Belarus",
    "UR": "Ukraine", "US": "Ukraine", "UT": "Ukraine", "UU": "Ukraine",
    "UW": "Ukraine", "UX": "Ukraine", "UY": "Ukraine", "UZ": "Ukraine",
    "ER": "Moldova", "4L": "Georgia", "EK": "Armenia", "4J": "Azerbaijan",
    "4K": "Azerbaijan", "TA": "Turkey", "TB": "Turkey", "TC": "Turkey",
    "5B": "Cyprus", "C4": "Cyprus", "H2": "Cyprus", "ZC4": "UK Bases Cyprus",
    "R": "European Russia", "U": "European Russia",
    "UA9": "Asiatic Russia", "UA0": "Asiatic Russia",
    "RA9": "Asiatic Russia", "RA0": "Asiatic Russia",
    "R9": "Asiatic Russia", "R0": "Asiatic Russia",
    "UA2": "Kaliningrad", "RA2": "Kaliningrad",
    # Africa
    "CN": "Morocco", "7X": "Algeria", "3V": "Tunisia", "5A": "Libya",
    "SU": "Egypt", "ST": "Sudan", "Z8": "South Sudan", "ET": "Ethiopia",
    "E3": "Eritrea", "J2": "Djibouti", "T5": "Somalia", "5Z": "Kenya",
    "5H": "Tanzania", "5X": "Uganda", "9U": "Burundi", "9X": "Rwanda",
    "9Q": "DR Congo", "TN": "Congo", "TL": "Central African Rep",
    "TT": "Chad", "TJ": "Cameroon", "TR": "Gabon", "3C": "Equatorial Guinea",
    "S9": "Sao Tome", "D2": "Angola", "9J": "Zambia", "Z2": "Zimbabwe",
    "C9": "Mozambique", "7Q": "Malawi", "V5": "Namibia", "A2": "Botswana",
    "3DA": "Eswatini", "7P": "Lesotho", "ZS": "South Africa",
    "ZR": "South Africa", "ZT": "South Africa", "ZU": "South Africa",
    "5R": "Madagascar", "3B8": "Mauritius", "3B9": "Rodrigues",
    "3B7": "St Brandon", "3B6": "Agalega", "S7": "Seychelles",
    "FR": "Reunion", "FH": "Mayotte", "D4": "Cape Verde",
    "6W": "Senegal", "C5": "Gambia", "J5": "Guinea-Bissau",
    "3X": "Guinea", "9L": "Sierra Leone", "EL": "Liberia",
    "TU": "Ivory Coast", "9G": "Ghana", "5V": "Togo", "TY": "Benin",
    "5U": "Niger", "5N": "Nigeria", "XT": "Burkina Faso", "TZ": "Mali",
    "5T": "Mauritania", "S0": "Western Sahara",
    # Asia
    "JA": "Japan", "JE": "Japan", "JF": "Japan", "JG": "Japan",
    "JH": "Japan", "JI": "Japan", "JJ": "Japan", "JK": "Japan",
    "JL": "Japan", "JM": "Japan", "JN": "Japan", "JO": "Japan",
    "JP": "Japan", "JQ": "Japan", "JR": "Japan", "JS": "Japan",
    "7J": "Japan", "7K": "Japan", "7L": "Japan", "7M": "Japan", "7N": "Japan",
    "8J": "Japan",
    "HL": "South Korea", "DS": "South Korea", "DT": "South Korea",
    "6K": "South Korea", "6L": "South Korea", "6M": "South Korea",
    "P5": "North Korea",
    "BY": "China", "BA": "China", "BD": "China", "BG": "China",
    "BH": "China", "BI": "China", "BT": "China", "B": "China",
    "BV": "Taiwan", "BX": "Taiwan", "BM": "Taiwan",
    "VR2": "Hong Kong", "XX9": "Macao",
    "VU": "India", "AT": "India", "8T": "India", "VU4": "Andaman Is",
    "VU7": "Lakshadweep", "4S": "Sri Lanka", "8Q": "Maldives",
    "S2": "Bangladesh", "9N": "Nepal", "A5": "Bhutan",
    "AP": "Pakistan", "AS": "Pakistan", "YA": "Afghanistan",
    "EP": "Iran", "YI": "Iraq", "9K": "Kuwait", "A9": "Bahrain",
    "A7": "Qatar", "A6": "United Arab Emirates", "A4": "Oman",
    "7O": "Yemen", "HZ": "Saudi Arabia", "7Z": "Saudi Arabia",
    "JY": "Jordan", "OD": "Lebanon", "YK": "Syria", "4X": "Israel",
    "4Z": "Israel", "E4": "Palestine",
    "UN": "Kazakhstan", "UP": "Kazakhstan", "EX": "Kyrgyzstan",
    "EY": "Tajikistan", "EZ": "Turkmenistan", "UK": "Uzbekistan",
    "JT": "Mongolia", "XU": "Cambodia", "XW": "Laos", "XZ": "Myanmar",
    "HS": "Thailand", "E2": "Thailand", "3W": "Vietnam", "XV": "Vietnam",
    "9M2": "West Malaysia", "9M6": "East Malaysia", "9M": "West Malaysia",
    "9V": "Singapore", "V8": "Brunei",
    "YB": "Indonesia", "YC": "Indonesia", "YD": "Indonesia",
    "YE": "Indonesia", "YF": "Indonesia", "YG": "Indonesia",
    "YH": "Indonesia", "8A": "Indonesia", "8B": "Indonesia",
    "7A": "Indonesia", "7B": "Indonesia", "7C": "Indonesia",
    "DU": "Philippines", "DV": "Philippines", "DW": "Philippines",
    "DX": "Philippines", "DY": "Philippines", "DZ": "Philippines",
    "4W": "Timor-Leste",
    # Oceania
    "VK": "Australia", "AX": "Australia", "VI": "Australia",
    "VK9": "Australian External", "VK0": "Heard/Macquarie",
    "ZL": "New Zealand", "ZM": "New Zealand", "ZK": "New Zealand",
    "P2": "Papua New Guinea", "H4": "Solomon Is", "YJ": "Vanuatu",
    "3D2": "Fiji", "5W": "Samoa", "A3": "Tonga", "E5": "Cook Is",
    "FO": "French Polynesia", "FK": "New Caledonia", "FW": "Wallis & Futuna",
    "T2": "Tuvalu", "T30": "W Kiribati", "T31": "C Kiribati",
    "T32": "E Kiribati", "T33": "Banaba", "C2": "Nauru", "V7": "Marshall Is",
    "V6": "Micronesia", "T8": "Palau", "KH1": "Baker/Howland",
    "KH3": "Johnston", "KH4": "Midway", "KH5": "Palmyra",
    "KH7K": "Kure", "KH9": "Wake", "ZL7": "Chatham Is", "ZL8": "Kermadec",
    "ZL9": "NZ Subantarctic",
    # Antarctic / remote
    "CE9": "Antarctica", "KC4": "Antarctica", "VP8H": "South Shetland",
    "3Y": "Bouvet/Peter I", "FT": "French Southern",
    "VP9": "Bermuda", "VP5": "Turks & Caicos", "V4": "St Kitts & Nevis",
    "ZD7": "St Helena", "ZD8": "Ascension", "ZD9": "Tristan da Cunha",
    "VP2": "British Caribbean", "PJ5": "Sint Eustatius",
}

_SORTED = sorted(PREFIXES.items(), key=lambda kv: -len(kv[0]))
_STRIP = re.compile(r"^(?:<|>)+|(?:<|>)+$")


def entity(call):
    """Best-effort DXCC entity for a callsign."""
    if not call:
        return None
    c = _STRIP.sub("", call).upper()
    # portable suffix wins when it is a real prefix (e.g. W1AW/8 stays USA,
    # but DL1ABC/W would be USA) -- only honour alpha-leading suffixes
    if "/" in c:
        head, _, tail = c.partition("/")
        if tail and tail not in ("P", "M", "MM", "AM", "QRP") and not tail.isdigit():
            c = tail
        else:
            c = head
    for pfx, name in _SORTED:
        if c.startswith(pfx):
            return name
    return None
