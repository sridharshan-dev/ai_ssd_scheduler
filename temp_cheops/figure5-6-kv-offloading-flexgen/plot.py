import matplotlib
import matplotlib.pyplot as plt

# Switch to Type 1 Fonts.
# Type 1 font
plt.rc('font', **{'family': 'serif', 'serif': ['Times']})
matplotlib.rcParams['pdf.fonttype'] = 42
matplotlib.rcParams['ps.fonttype'] = 42
plt.rc('pdf', use14corefonts=True, fonttype=42)
plt.rc('ps', useafm=True, fonttype=42)

# Font size
def set_fontsize(fontsize):
    plt.rc('text', usetex=True)
    plt.rc('font', size=fontsize, weight="bold", family='serif', serif='cm10')
    plt.rc('axes', labelsize=fontsize,labelweight="bold")    
    plt.rc('xtick', labelsize=fontsize)    
    plt.rc('ytick', labelsize=fontsize)    
    plt.rc('legend', fontsize=fontsize)  
set_fontsize(28)

def make_text_bold(text):
    return r'\textbf{' + text + r'}'

print("TYPE 1 FONTS ENABLED")

m_color_index = 0
matplotlib_color = [
    '#4477AA', '#228833', '#CCBB44', '#EE6677', '#AA3377', '#66CCEE',
    '#BBBBBB', '#332288'
]
dot_style = [
    '+',
    'X',
    'o',
    'v',
    's',
    'P',
]


def get_next_color():
    global m_color_index
    c = matplotlib_color[m_color_index % len(matplotlib_color)]
    m_color_index += 1

    return c


def reset_color():
    global m_color_index
    m_color_index = 0
