"""Small gazetteer: find which country a headline is about, and its continent.

Format per line:  Country|Continent|alias1,alias2,...
The country name itself is always an alias. Matching is case-sensitive on whole words,
and the earliest match in the text wins.
"""
import re

SPEC = """
India|Asia|Indian,Delhi,New Delhi,Modi,Mumbai,Bengaluru,Kolkata,Chennai
Pakistan|Asia|Pakistani,Islamabad,Karachi,Lahore
Bangladesh|Asia|Dhaka,Bangladeshi
Sri Lanka|Asia|Colombo,Sri Lankan
Nepal|Asia|Kathmandu,Nepali
Bhutan|Asia|Thimphu
Maldives|Asia|Maldivian
Afghanistan|Asia|Kabul,Taliban,Afghan
China|Asia|Chinese,Beijing,Xi Jinping,Shanghai
Japan|Asia|Japanese,Tokyo
South Korea|Asia|South Korean,Seoul
North Korea|Asia|Pyongyang,Kim Jong Un,North Korean
Taiwan|Asia|Taipei,Taiwanese
Hong Kong|Asia|
Mongolia|Asia|Ulaanbaatar
Singapore|Asia|Singaporean
Malaysia|Asia|Malaysian,Kuala Lumpur
Indonesia|Asia|Indonesian,Jakarta
Thailand|Asia|Thai,Bangkok
Vietnam|Asia|Vietnamese,Hanoi
Philippines|Asia|Filipino,Manila
Myanmar|Asia|Burma,Naypyidaw
Cambodia|Asia|Phnom Penh
Laos|Asia|Vientiane
Iran|Asia|Iranian,Tehran
Iraq|Asia|Iraqi,Baghdad
Israel|Asia|Israeli,Tel Aviv,Jerusalem,Netanyahu,IDF
Palestine|Asia|Gaza,West Bank,Palestinian,Hamas,Palestinians
Lebanon|Asia|Beirut,Hezbollah,Lebanese
Syria|Asia|Damascus,Syrian
Jordan|Asia|Amman,Jordanian
Saudi Arabia|Asia|Riyadh,Saudi
United Arab Emirates|Asia|UAE,Dubai,Abu Dhabi,Emirati
Qatar|Asia|Doha,Qatari
Kuwait|Asia|Kuwaiti
Bahrain|Asia|Manama
Oman|Asia|Muscat,Omani
Yemen|Asia|Houthi,Houthis,Sanaa,Yemeni
Turkey|Asia|Turkiye,Ankara,Erdogan,Turkish,Istanbul
Kazakhstan|Asia|Astana
Uzbekistan|Asia|Tashkent
Armenia|Asia|Yerevan,Armenian
Azerbaijan|Asia|Baku,Azerbaijani
United Kingdom|Europe|UK,Britain,British,England,Scotland,Wales,London,Starmer,Westminster
Ireland|Europe|Irish,Dublin
France|Europe|French,Paris,Macron
Germany|Europe|German,Berlin
Italy|Europe|Italian,Rome
Spain|Europe|Spanish,Madrid,Barcelona
Portugal|Europe|Portuguese,Lisbon
Netherlands|Europe|Dutch,Amsterdam,The Hague
Belgium|Europe|Belgian,Brussels
Switzerland|Europe|Swiss,Geneva,Zurich
Austria|Europe|Austrian,Vienna
Sweden|Europe|Swedish,Stockholm
Norway|Europe|Norwegian,Oslo
Denmark|Europe|Danish,Copenhagen
Finland|Europe|Finnish,Helsinki
Iceland|Europe|Icelandic,Reykjavik
Poland|Europe|Polish,Warsaw
Ukraine|Europe|Kyiv,Kiev,Ukrainian,Zelensky,Zelenskyy
Russia|Europe|Moscow,Kremlin,Putin,Russian
Belarus|Europe|Minsk,Belarusian
Greece|Europe|Athens,Greek
Hungary|Europe|Budapest,Orban,Hungarian
Romania|Europe|Bucharest,Romanian
Czech Republic|Europe|Czechia,Prague,Czech
Serbia|Europe|Belgrade,Serbian
Croatia|Europe|Zagreb,Croatian
Bulgaria|Europe|Sofia,Bulgarian
Slovakia|Europe|Bratislava,Slovak
Lithuania|Europe|Vilnius,Lithuanian
Latvia|Europe|Riga,Latvian
Estonia|Europe|Tallinn,Estonian
Moldova|Europe|Chisinau,Moldovan
Egypt|Africa|Cairo,Egyptian
Nigeria|Africa|Lagos,Abuja,Nigerian
South Africa|Africa|Johannesburg,Pretoria,Cape Town,Springboks,Proteas,Bafana Bafana
Kenya|Africa|Nairobi,Kenyan
Ethiopia|Africa|Addis Ababa,Ethiopian
Ghana|Africa|Accra,Ghanaian
Tanzania|Africa|Dodoma,Tanzanian,Dar es Salaam
Uganda|Africa|Kampala,Ugandan
Rwanda|Africa|Kigali,Rwandan
Sudan|Africa|Khartoum,Sudanese
South Sudan|Africa|Juba
Libya|Africa|Tripoli,Libyan
Algeria|Africa|Algiers,Algerian
Morocco|Africa|Rabat,Moroccan,Casablanca
Tunisia|Africa|Tunis,Tunisian
Somalia|Africa|Mogadishu,Somali
DR Congo|Africa|Democratic Republic of the Congo,DRC,Kinshasa,Congolese
Zimbabwe|Africa|Harare,Zimbabwean
Zambia|Africa|Lusaka,Zambian
Mozambique|Africa|Maputo
Angola|Africa|Luanda,Angolan
Senegal|Africa|Dakar,Senegalese
Mali|Africa|Bamako,Malian
Niger|Africa|Niamey
Cameroon|Africa|Yaounde,Cameroonian
Ivory Coast|Africa|Cote d'Ivoire,Abidjan
Madagascar|Africa|Antananarivo
Namibia|Africa|Windhoek,Namibian
Botswana|Africa|Gaborone
United States|North America|US,U.S.,USA,America,American,Americans,Washington,White House,Pentagon,Trump,Congress,Senate,New York,California,Texas
Canada|North America|Canadian,Ottawa,Toronto,Vancouver
Mexico|North America|Mexican,Mexico City
Cuba|North America|Havana,Cuban
Haiti|North America|Haitian
Jamaica|North America|Jamaican,Kingston
Panama|North America|Panamanian
Costa Rica|North America|San Jose
Guatemala|North America|Guatemalan
Honduras|North America|Honduran
Nicaragua|North America|Nicaraguan
El Salvador|North America|Salvadoran
Dominican Republic|North America|Santo Domingo
Brazil|South America|Brazilian,Brasilia,Rio de Janeiro,Sao Paulo
Argentina|South America|Argentine,Argentinian,Buenos Aires,Milei
Chile|South America|Chilean,Santiago
Colombia|South America|Colombian,Bogota
Peru|South America|Peruvian,Lima
Venezuela|South America|Venezuelan,Caracas,Maduro
Ecuador|South America|Ecuadorian,Quito
Bolivia|South America|Bolivian,La Paz
Uruguay|South America|Uruguayan,Montevideo
Paraguay|South America|Paraguayan,Asuncion
Guyana|South America|Georgetown
Australia|Oceania|Australian,Canberra,Sydney,Melbourne,Aussie,Aussies,Brisbane,Perth
New Zealand|Oceania|NZ,Wellington,Auckland,Kiwi,Kiwis,All Blacks
Papua New Guinea|Oceania|Port Moresby
Fiji|Oceania|Suva,Fijian
Samoa|Oceania|Apia
Tonga|Oceania|Nuku'alofa
"""

COUNTRY_CONTINENT = {}
_ALIAS = {}
for _line in SPEC.strip().splitlines():
    _name, _cont, _aliases = _line.split("|")
    COUNTRY_CONTINENT[_name] = _cont
    for _a in [_name] + [a for a in _aliases.split(",") if a]:
        _ALIAS[_a] = _name

_PATTERN = re.compile(
    r"(?<![\w])(" + "|".join(re.escape(a) for a in sorted(_ALIAS, key=len, reverse=True)) + r")(?![\w])"
)


def find_country(*texts):
    """Return (country, continent) for the earliest alias found, trying texts in order."""
    for text in texts:
        m = _PATTERN.search(text or "")
        if m:
            name = _ALIAS[m.group(1)]
            return name, COUNTRY_CONTINENT[name]
    return None, None
