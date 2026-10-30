import re

corridors = {
    'India (IST)': r'\b(india|bengaluru|bangalore|hyderabad|pune|delhi|gurgaon|noida|mumbai|chennai)\b',
    'Singapore / APAC (SGT)': r'\b(singapore|sg|hong kong|tokyo|japan|sydney|australia|melbourne|seoul|korea)\b',
    'UAE (GST)': r'\b(dubai|abu dhabi|uae|emirates|qatar|doha|riyadh|saudi)\b',
    'Europe (CEST)': r'\b(germany|berlin|munich|frankfurt|switzerland|zurich|france|paris|netherlands|amsterdam|gmbh)\b',
    'UK (BST)': r'\b(united kingdom|uk|london|england|scotland|wales|britain)\b',
    'US East (EDT)': r'\b(new york|nyc|boston|atlanta|miami|washington|toronto|canada)\b',
    'US West (PDT)': r'\b(san francisco|sf|bay area|silicon valley|seattle|california|los angeles|austin|texas|chicago)\b'
}

test_strings = [
    ('tasks in queue and bug in code', 'Should be None'),
    ('Located in Berlin, Germany working at TONEART GmbH', 'Should be Europe'),
    ('Working from London, UK', 'Should be UK'),
    ('Bengaluru tech hub engineer', 'Should be India'),
    ('Building in Singapore', 'Should be Singapore')
]

for text, expected in test_strings:
    matched = None
    for name, pattern in corridors.items():
        if re.search(pattern, text.lower()):
            matched = name
            break
    print(f'Text: "{text}" -> Matched: {matched} ({expected})')
