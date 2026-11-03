"""Display flags from explicit exported nationality suffixes; never infer from names."""

NATIONALITY_CODES = {
    "Albanian":"AL", "Algerian":"DZ", "American":"US", "Angolan":"AO",
    "Antiguan & Barbudan":"AG", "Argentinian":"AR", "Australian":"AU", "Austrian":"AT",
    "Belarusian":"BY", "Belgian":"BE", "Bermudian":"BM", "Bissau-Guinean":"GW",
    "Bosnian":"BA", "Brazilian":"BR", "Bulgarian":"BG", "Burkinabé":"BF", "Burkinab�":"BF",
    "Cameroonian":"CM", "Canadian":"CA", "Cape Verdean":"CV", "Chilean":"CL",
    "Colombian":"CO", "Comoran":"KM", "Croatian":"HR", "Cuban":"CU",
    "Curaçaoan":"CW", "Cura�aoan":"CW", "Cypriot":"CY", "Czech":"CZ", "DR Congolese":"CD",
    "Danish":"DK", "Dominican Republic":"DO", "Dutch":"NL", "Ecuadorian":"EC",
    "Egyptian":"EG", "English":"gbeng", "Estonian":"EE", "Filipino":"PH",
    "Finnish":"FI", "French":"FR", "Gabonese":"GA", "Gambian":"GM", "Georgian":"GE",
    "German":"DE", "Ghanaian":"GH", "Greek":"GR", "Grenadian":"GD", "Guatemalan":"GT",
    "Guinean":"GN", "Haitian":"HT", "Hungarian":"HU", "Icelandic":"IS", "Indian":"IN",
    "Indonesian":"ID", "Iranian":"IR", "Iraqi":"IQ", "Irish":"IE", "Israeli":"IL",
    "Italian":"IT", "Ivorian":"CI", "Jamaican":"JM", "Japanese":"JP",
    "Kittian & Nevisian":"KN", "Kosovan":"XK", "Luxembourger":"LU", "Macedonian":"MK",
    "Malagasy":"MG", "Malian":"ML", "Mauritanian":"MR", "Mexican":"MX", "Moldovan":"MD",
    "Montenegrin":"ME", "Moroccan":"MA", "New Zealand":"NZ", "Nigerian":"NG",
    "Northern Irish":"GB", "Norwegian":"NO", "Panamanian":"PA", "Paraguayan":"PY",
    "Peruvian":"PE", "Polish":"PL", "Portuguese":"PT", "Romanian":"RO", "Saint Lucian":"LC",
    "Scottish":"gbsct", "Senegalese":"SN", "Serbian":"RS", "Sierra Leonean":"SL",
    "Slovak":"SK", "South African":"ZA", "South Korean":"KR", "Spanish":"ES",
    "Surinamese":"SR", "Swedish":"SE", "Swiss":"CH", "Togolese":"TG", "Trinbagonian":"TT",
    "Tunisian":"TN", "Turkish":"TR", "Ukrainian":"UA", "Uruguayan":"UY", "Welsh":"gbwls",
    "Zambian":"ZM", "Zimbabwean":"ZW",
}


def nationality_flag(code):
    if len(code)==2:
        return "".join(chr(0x1F1E6+ord(letter)-ord("A")) for letter in code.upper())
    return "\U0001f3f4"+"".join(chr(0xE0000+ord(letter)) for letter in code)+"\U000e007f"


def name_with_flag(raw):
    name,separator,nationality = raw.rpartition(" - ")
    code = NATIONALITY_CODES.get(nationality.strip())
    if separator and name.strip() and code:
        return f"{name.strip()} {nationality_flag(code)}"
    return raw
