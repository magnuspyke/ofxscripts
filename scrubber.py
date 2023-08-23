# scrubber.py
# http://sites.google.com/site/pocketsense/
# fix known issues w/ OFX downloads
# rlc: 2010

# 05-Aug-2010*rlc
# - Added _scrubTime() function to fix NULL time stamps so that transactions record on the correct date
#   regardless of time zone.
# 28-Jan-2011*rlc
#   - Added _scrubDTSTART() to fix missing <DTEND> fields when a <DTSTART> exists.
#   - Recoded scrub routines to use regex substitutions
# 28-Aug-2012*rlc
#   - Added quietScrub option to sites.dat (suppresses scrub messages)
# 02-Feb-2013*rlc
#   - Bug fix in _scrubDTSTART
#   - Added scrub routine to verify Investment buy and sell transactions
# 17-Feb-2013*rlc
#   - Added scrub routine for CORRECTACTION and CORRECTFITID tags (not supported by Money)
# 06-Jul-2013*rlc
#   - Bug fix in _scrubDTSTART()
# 20-Feb-2014*rlc
#   - Bug fix in _scrubINVsign() for SELL transactions
#14-Aug-2016*rlc
#   - Update to handle new Discover Bank FITID format.
#11-Mar-2017*rlc
#   - Added REINVEST transactions to _scrubINVsign()
#   - Added _scrubRemoveZeroTrans().  Removes $0.00 transactions when enabled in sites.dat
#08-Apr-2017*cgn / rlc
#   - Revert _scrubINVsign() to previous version
#   - Add _scrubREINVESTsign() to handle REINVEST transactions separately 
#     Note the differnt field order vs what's used for BUY/SELL transactions in _scrubINVsign()
#27-Aug-2017*rlc
#   - Bug patch to fix timedelta call
#24-Oct-2017*ad / rlc
#   - Update to address recent change by Discover Bank re transaction ids
#   - Insert check# field for discover bank transactions such that Money recognizes it
#01-Jan-2018*rlc
#   - Revert Discover Bank fitid substitution to the same as it was before the 24-Oct update
#14-Apr-2018*rlc
#   - Replace ampsersand "&" symbol w/ &amp; code when not part of valid escape code. see _scrubGeneral()
#27-Jul-2018*dbc
#   - Add TRowePrice scrub function to fix paid-out dividends/cap gains that are marked as reinvested
#14-Feb-2021*cgn
#   - add REFNUM and SIC fields to general scrub routine
#   - add _scrubHeader() to remove spaces after colon if present
#14-Feb-2021*rlc
#   - add support for site-specific skipZeroTrans option.
#   - add "replace null or missing <TRNTYPE> with 'OTHER'" to _scrubGenera()
#27-Mar-2021*cgn
#  - open ofx file w/ 'U' qualifier.  Forces newlines to match Windows convention (e.g., \n = <CR><LF>)
#19Jun2023*rlc
#   - add logging

import os, sys, re, glob, logging
import site_cfg
from datetime import datetime, timedelta
from control2 import *
from rlib1 import *

log = logging.getLogger('root')

userdat = site_cfg.site_cfg()
stat = False    #global used between re lambda subs to track status

def scrubPrint(line):
    if not userdat.quietScrub:
        log.info("+ %s" % line)
    
def scrub(filename, site):
    #filename = string
    #site = DICT structure containing full site info from sites.dat
 
    siteURL = FieldVal(site, 'url').upper()
    dtHrs = FieldVal(site, 'timeOffset')
    accType = FieldVal(site, 'CAPS')[1]
    site_skip_zt = FieldVal(site, 'skipzerotrans')
    with open(filename, newline='') as f:
        ofx = f.read()  #as-found ofx message
       
    ofx = _scrubHeader(ofx) #Remove illegal spaces in OFX header lines
    
    ofx= _scrubTime(ofx)     #fix 000000 and NULL datetime stamps 

    if dtHrs != 0: ofx = _scrubShiftTime(ofx, dtHrs)   #note: always call *after* _scrubTime()
    
    ofx= _scrubDTSTART(ofx)  #fix missing <DTEND> fields
      
    #fix malformed investment buy/sell/reinvest signs (neg vs pos), if they exist
    if "<INVSTMTTRNRS>" in ofx.upper(): 
        ofx= _scrubINVsign(ofx)  
        ofx= _scrubREINVESTsign(ofx)  
	
    #remove $0.00 transactions
    if (userdat.skipZeroTransactions or site_skip_zt) and not site_skip_zt==False: 
        ofx = _scrubRemoveZeroTrans(ofx)
    
    #perform general ofx cleanup
    ofx = _scrubGeneral(ofx)

    #run custom srub routines
    #any scrub_*.py file found in the current folder will be processed
    for scrubFile in glob.glob('scrub_*.py'):
        scrublet = scrubFile.strip('.py')
        try:
            s = __import__(scrublet) 
            ofx2 = s.scrub(ofx, siteURL, accType)
            if validOFX(ofx2) == '': 
                ofx=ofx2
            else: 
                scrubPrint(scrubFile + ' ERROR: Custom scrub_*.py files must return a valid OFX message.')
        except Exception as e:
            log.exception('An error occurred when processing scrub module: %s' % scrublet)
            
    #write the new version to the same file
    with open(filename, 'w') as f:
        f.write(ofx)

#--------------------------------    
def _scrubTime(ofx):
    #Replace NULL time stamps with noontime (12:00)

    #regex p captures everything from <DT*> up to the next <tag>, but excludes the next "<".
    #p produces 2 results:  group(1) = <DT*> field, group(2)=dateval
    p = re.compile(r'(<DT.+?>)([^<\s]+)', re.IGNORECASE)
    #call date correct function (inline lamda, takes regex result = r tuple)
    
    global stat
    stat = False
    ofx_final = p.sub(lambda r: _scrubTime_r1(r), ofx)
    if stat: scrubPrint("Scrubber: Null time values updated.")
    
    return ofx_final

def _scrubTime_r1(r):
    # Replace zero and NULL time fields with a "NOON" timestamp (120000)
    # Force "date" to be the same as the date listed, regardless of time zone by setting time to NOON.
    # Applies when no time is given, and when time == MIDNIGHT (000000)
    global stat
    fieldtag = r.group(1)
    DT = r.group(2).strip(' ')      #date+time
    
    # Full date/time format example:  20100730000000.000[-4:EDT]
    if DT[8:] == '' or DT[8:14] == '000000':
        #null time given.  Adjust to 120000 value (noon).
        DT = DT[:8] + '120000'
        stat = True
        
    return fieldtag + DT

#--------------------------------    
def _scrubDTSTART(ofx):
    # <DTSTART> field for an account statement must have a matching <DTEND> field
    # If DTEND is missing, insert <DTEND>="now"
    # The assumption is made that only one statement exists in the OFX file (no multi-statement files!)
    
    ofx_final = ofx
    now = datetime.now()
    nowstr = now.strftime("%Y%m%d%H%M00")
    
    if ofx.find('<DTSTART>') >= 0 and ofx.find('<DTEND>') < 0:
        #we have a dtstart, but no dtend... fix it.
        scrubPrint("Scrubber: Fixing missing <DTEND> field")
        
        #regex p captures everything from <DTSTART> up to the next <tag> or white space into group(1)
        p = re.compile(r'(<DTSTART>[^<\s]+)', re.IGNORECASE)
        if Debug: log.debug('DTSTART: findall()=%s' % p.findall(ofx_final))
        #replace group1 with (group1 + <DTEND> + datetime)
        ofx_final = p.sub(r'\1<DTEND>'+nowstr, ofx_final)
    
    return ofx_final

def _scrubShiftTime(ofx, h):
    #Shift DTASOF time values by (float) h hours
    #Added: 15-Feb-2011, rlc
    
    #regex p captures everything from <DTASOF> up to the next <tag> or white-space.
    #p produces 2 results:  group(1) = <DTASOF> field, group(2)=dateval
    p = re.compile(r'(<DTASOF>)([^<\s]+)', re.IGNORECASE | re.DOTALL)
    
    #call date correct function (inline lamda, takes regex result = r tuple)
    if p.search(ofx): 
        scrubPrint("Scrubber: Shifting DTASOF time values " + str(h) + " hours.")
        ofx_final = p.sub(lambda r: _scrubShiftTime_r1(r,h), ofx)    

    return ofx_final

def _scrubShiftTime_r1(r,h):
    #Shift time value by (float) h hours for regex search result r.
    #Added: 15-Feb-2011, rlc
    
    fieldtag = r.group(1)       #date field tag (e.g., <DTASOF>)
    DT = r.group(2).strip(' ')  #date+time

    if Debug: log.debug('fieldtag=%s | DT=%s' % (fieldtag, DT))
    
    # Full date/time format example:  20100730120000.000[-4:EDT]
    #separate into date/time + timezone
    tz = ""
    if '[' in DT:
        p = DT.index('[')
        tz = DT[p:]
        DT = DT[:p]
    
    #strip the decimal fraction, if we have it
    if '.' in DT:
        d  = DT.index('.')
        DT = DT[:d]
        
    if Debug: log.debug('New DT=%s | tz=%s' % (DT, tz))
    
    #shift the time
    tval = datetime.strptime(DT,"%Y%m%d%H%M%S")  #convert str to datetime
    deltaT = timedelta(hours=h)    
    tval += deltaT                                        #add hours
    DT = tval.strftime("%Y%m%d%H%M%S") + tz               #convert new datetime to str
        
    return fieldtag + DT

def _scrubINVsign(ofx):
    #Fix malformed parameters in Investment buy/sell sections, if they exist
    #Issue  first noticed with Fidelity netbenefits 401k accounts:  rlc*2013
    
    #BUY transactions:
    #   UNITS must be positive
    #   TOTAL must be negative
    
    #SELL transactions:
    #   UNITS must be negative
    #   TOTAL must be positive
    
    global stat
    stat = False
    p = re.compile(r'(<INVBUY>|<INVSELL>)(.+?<UNITS>)(.+?)(<.+?<TOTAL>)([^<]+)', re.IGNORECASE | re.DOTALL)
    ofx_final=p.sub(lambda r: _scrubINVsign_r1(r), ofx)
    if stat:
        scrubPrint("Scrubber: Invalid investment sign (pos/neg) found.  Corrected.")
    
    return ofx_final
    
def _scrubINVsign_r1(r):
    
    global stat
    type=""
    if "INVBUY"  in r.group(1): type = "INVBUY"
    if "INVSELL" in r.group(1): type = "INVSELL"
    qty = r.group(3)
    total=r.group(5)
	
    qty_v=float2(qty)
    total_v=float2(total)
    
    if (type=="INVBUY" and qty_v<0) or (type=="INVSELL" and qty_v>0):
        stat=True
        qty=str(-1*qty_v)

    if (type=="INVBUY" and total_v>0) or (type=="INVSELL" and total_v<0):
        stat=True
        total=str(-1*total_v)
    
    return r.group(1) + r.group(2) + qty + r.group(4) + total

def _scrubREINVESTsign(ofx):
    #Fix malformed parameters in REINVEST transactions, if they exist
    #Issue  first noticed with Fidelity netbenefits 401k accounts:  cgn*2016
    
    #REINVEST transactions:
    #   UNITS must be positive
    #   TOTAL must be negative

    global stat
    stat=False
    p = re.compile(r'(<REINVEST>)(.+?<TOTAL>)(.+?)(<.+?<UNITS>)([^<]+)', re.IGNORECASE | re.DOTALL)
    ofx_final=p.sub(lambda r: _scrubREINVESTsign_r1(r), ofx)
    if stat:
        scrubPrint("  +Scrubber: Invalid reinvestment sign (pos/neg) found.  Corrected.")
    
    return ofx_final
    
def _scrubREINVESTsign_r1(r):
    global stat
    qty = r.group(5)
    total=r.group(3)
	
    qty_v=float2(qty)
    total_v=float2(total)
    
    if (qty_v<0):
        stat=True
        qty=str(-1*qty_v)

    if (total_v>0):
        stat=True
        total=str(-1*total_v)
    
    return r.group(1) + r.group(2) + total + r.group(4) + qty
    
def _scrubGeneral(ofx):    
    # General scrub routine for general updates  
    
    #1. Remove tag/value pairs that Money doesn't support
    #define unsupported tags that we've had trouble with
    global stat
    uTags = []    
    uTags.append('CORRECTACTION')
    uTags.append('CORRECTFITID')
    uTags.append('REFNUM')
    uTags.append('SIC')
    
    for tag in uTags:
        # Remove open tag and value
        p = re.compile(r'<'+tag+'>[^<]*', re.IGNORECASE) 
        if p.search(ofx):
            ofx = p.sub('',ofx)
            scrubPrint("Scrubber: <"+tag+"> tags removed.  Not supported by Money.")
        # Remove close tag (if any) [could probably create a very smart RE to merge these two REs]
        p = re.compile(r'</'+tag+'>',re.IGNORECASE)
        if p.search(ofx):
            ofx = p.sub('',ofx)
            scrubPrint("Scrubber: </"+tag+"> closing tags removed.")
    
    #2. Replace ampersands '&' that aren't part of a valid escape code (i.e., is NOT like &amp;, &#012; etc)
    #   literally:  replace '&' chars with '&amp;' when the next chars are not
    #               a '#' or valid alphanumerics followed by a ;
    p = re.compile(r'&(?!#?\w+;)')
    if p.search(ofx):
        scrubPrint("Scrubber: Replace invalid '&' chars with '&amp;'")
        ofx = p.sub('&amp;',ofx)

    #3. Replace null or missing <TRNTYPE> with 'OTHER'
    #   regex captures <TRNTYPE>, value, and first '<' or white space char
    p = re.compile(r'(<TRNTYPE>)(.*?)([<\s])', re.IGNORECASE)
    if p.search(ofx):
        stat=False
        ofx = p.sub(lambda r: _scrubGeneral_r1(r), ofx)
        if stat: scrubPrint("Null or missing TRNTYPE replaced with 'OTHER' ")
    return ofx

def _scrubGeneral_r1(r):
    # replace null or missing TRNTYPE with 'OTHER'
    global stat
    trntype = r.group(2)
    if trntype.upper() in ('NULL',''):
        trntype='OTHER'
        stat=True
    return r.group(1) + trntype + r.group(3)

def _scrubRemoveZeroTrans(ofx):
    #Remove transactions with a $0.00 value

    #regex p captures transaction records
    #p produces 3 results:  group(1) = trans header, group(2)=Amount, group(3)=trans suffix

    global stat
    stat=False
    p = re.compile(r'(<STMTTRN>.*?<TRNAMT>)(.+?)(<.*?</STMTTRN>)', re.DOTALL | re.IGNORECASE)

    ofx = p.sub(lambda r: _scrubRemoveZeroTrans_r1(r), ofx)    
    if stat: scrubPrint('Zero amount ($0.00) transactions removed.')
    return ofx
    
def _scrubRemoveZeroTrans_r1(r):
    # return null transaction when amount=0
    global stat
    amount = float2(r.group(2))
    if amount==0: stat=True
    return None if amount==0 else r.group(1)+r.group(2)+r.group(3) 
 
def _scrubHeader(ofx):
    # Look for header lines that have space after the colon. 
    #(we look based on format, in theory the RE could find them in the wrong place)
    p = re.compile(r'(^[^<:\n]+:)(\s)([^\n]+)', re.MULTILINE) 
    if p.search(ofx):
        # Remove the space 
        result = p.subn(r'\1\3',ofx)
        ofx = result[0]
        scrubPrint("Scrubber: Removed spaces in " + str(result[1]) + " header lines.")
    return ofx
