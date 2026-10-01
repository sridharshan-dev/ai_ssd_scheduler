with open('tempo_dashboard/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Marker before Tab 3
marker1 = '<!-- =========================================================================\n             TAB 3: CO-DESIGN ARCHITECTURE'
# Marker at script tag
marker2 = '<script src="real_cheops_trace.js"></script>'

idx1 = text.find(marker1)
idx2 = text.find(marker2)

if idx1 != -1 and idx2 != -1:
    cleaned = text[:idx1] + '</div>\n\n    ' + text[idx2:]
    with open('tempo_dashboard/index.html', 'w', encoding='utf-8') as f:
        f.write(cleaned)
    print("SUCCESS: index.html streamlined to 2 core presentation tabs.")
else:
    print(f"FAILED to find markers: idx1={idx1}, idx2={idx2}")
