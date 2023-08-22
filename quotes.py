# quotes.py
# http://sites.google.com/site/pocketsense/
#
# Original Version: TFB (http://thefinancebuff.com)
#
# This script retrieves price quotes for a list of stock and mutual fund ticker symbols from Yahoo! Finance.
# It creates a dummy OFX file and then imports the file to the default application associated with the .ofx extension.
# I wrote this script in order to use Microsoft Money after the quote downloading feature is disabled by Microsoft.
#
# For more information, see
#    http://thefinancebuff.com/2009/09/security-quote-script-for-microsoft-money.html

# History
# -----------------------------------------------------
# 04-Mar-2010*rlc 
#   - Initial changes/edits for incorporation w/ the "pocketsense" pkg (formatting, method of call, etc.)
#   - Examples:
#       - Debug control
#       - use .\xfr for data
#       - moved stock/fund ticker symbols to sites.dat, separating user info from the code
# 18-mar-2010*rlc
#   - Skip stock/fund symbols that aren't recognized by Yahoo! Finance (rather than throw an error)
# 07-May-2010*rlc
#   - Try not to bomb if the server connection fails or times out and set return STATUS accordingly
#   - Changed output file format to QUOTES+time$.ofx
# 09-Sep-2010*rlc
#   - Add support for alternate Yahoo! quote site URL (defined in sites.dat as YahooURL: url)
#   - Use CSV utility to parse csv data
#   - Write out quote history file to quotes.csv
# 12-Oct-2010*rlc
#   - Fixed bug in QuoteHistory date field
# 24-Nov-2010*rlc
#   - Skip quotes with missing parameters.  Otherwise, Money mail throw an error during import.
#   - Add an "account balance" data field of zero (balance=0) for the overall statement.
# 10-Jan-2010*rlc
#   - Write quote summary to xfrdir\quotes.htm
#   - Moved _header, OfxField, OfxTag, _genuid, and OfxDate functions to rLib1
#   - Removed "\r" from linebreaks.
#       Will reuse when combining statements
# 18-Feb-2011*rlc:
#   - Use ticker symbol when stock name from Yahoo is null
#   - Added Cal's yahoo screen scraper for symbols not available via the csv interface
#   - Added YahooTimeZone option
#   - Added support for quote multiplier option
# 22-Mar-2011*rlc:
#   - Added support for alternate ticker symbol to send to Money (instead of Yahoo symbol)
#     Default symbol = Yahoo ticker
# 03Sep2013*rlc
#   - Modify to support European versions of MS Money 2005 (and probably 2003/2004)
#     * Added INVTRANLIST tag set
#     * Added support for forceQuotes option.  Force additional quote reponse to adjust 
#       shares held to non-zero and back.
#   - Updated YahooScrape code for updated Yahoo html screen-formatting
# 19Jul2013*rlc
#   - Bug fix.  Strip commas from YahooScrape price results
#   - Added YahooScrape support for quote symbols with a '^' char (e.g., ^DJI)
# 21Oct2013*rlc
#   - Added support for quoteAccount
# 09Jan2014*rlc
#   - Fixed bug related to ForceQuotes and change of calendar year.
# 19Jan2014*rlc:  
#   -Added support for EnableGoogleFinance option
#   -Reworked the way that quotes are retrieved, to improve reliability
# 14Feb2014*rlc:
#   -Extended url timeout.  Some ex-US users were having issues.
#   -Fixed bug that popped up when EnableYahooFinace=No
# 25Feb2014*rlc:
#   -Changed try/catch for URLopen to catch *any* exception
# 14Sep2015*rlc
#   -Changed yahoo time parse to read hours in 24hr format
# 09Nov2017*rlc
#   -Replace Yahoo quotes csv w/ json
#   -Removed yahooScrape option
# 24Mar2018*rlc
#   -Use longName when available for Yahoo quotes.  Mutual fund *family* name is sometimes given as shortName (see vhcox as example)
# 20Feb2021*rlc
#   -Minor edits while implementing Requests pkg
# 25May2023*rlc
#   -Update to use Yahoo v10 service and cleanup json parse to remove csv-oriented format

import os, requests, re, json, pickle
import site_cfg
from control2 import *
from rlib1 import *
from datetime import datetime, timedelta

join = str.join

class Security:
    """
    Encapsulate a stock or mutual fund. A Security has a ticker, a name, a price quote, and 
    the as-of date and time for the price quote. Name, price and as-of date and time are retrieved
    from Yahoo! Finance.
    
    fields:
        status, source, ticker, name, price, quoteTime, pclose, pchange
    """

    def __init__(self, item):
        #item = {"ticker":TickerSym, 'm':multiplier, 's':symbol}
        # TickerSym = symbol to grab from Yahoo
        # m         = multiplier for quote
        # s         = symbol to pass to Money

        self.ticker = item['ticker']
        self.multiplier = item['m']
        self.symbol = item['s']
        self.status = True
        
    def _removeIllegalChars(self, inputString):
        pattern = re.compile("[^a-zA-Z0-9 ,.-]+")
        return pattern.sub("", inputString)
        
    def getQuote(self):
        
        #Yahoo! Finance:  
        #parse data packet from standard htm page
        
        log.info('Getting quote for: %s' % self.ticker)
        
        self.status=False
        self.source='Y'
        #note: each try for a quote sets self.status=true if successful
        if eYahoo:
            self.getYahooQuote()
            if self.status: self.source='Y'
                        
        if not self.status:
            log.info('** %s: invalid quote response. Skipping.' % self.ticker)
            self.name = '*InvalidSymbol*'
        else:
            #show what we got
            name = self.ticker
            log.info('%s: %s %s %s %s' % (self.ticker, self.price, self.date, self.time, self.pchange))

                
    def getYahooQuote(self):
        #read Yahoo json data api, and return csv
        #returns: quote= [name, price, quoteTime, pclose, pchange], all as strings

        jsonURL = (YahooURL+'&crumb={crumb}').format(ticker=self.ticker, crumb=yahooCrumb)
        self.quoteURL = 'https://finance.yahoo.com/quote/{ticker}'.format(ticker=self.ticker)  #link to pretty view
        if Debug: log.debug('Reading ' + jsonURL)
        csvtxt=""
        self.status=True

        try:
            response=yahooSession.get(jsonURL)

        except:
            if Debug: log.debug('** Error reading %s' % self.quoteURL)
            self.status = False
        
        if self.status:
            try:
                ht = response.text.encode('ascii', 'ignore')
                pdata = json.loads(ht)
                quote = pdata['quoteSummary']['result'][0]['price']
                self.name = quote['shortName'] or quote['longName'] or ''
                self.name = self._removeIllegalChars(self.name)
                if self.name.strip()=='': self.name = quote['symbol']
                self.price = '%.2f' % (quote['regularMarketPrice']['raw'] * self.multiplier)
                self.pchange = quote['regularMarketChangePercent']['fmt']
                self.datetime= datetime.fromtimestamp(quote['regularMarketTime'])
                self.date=self.datetime.strftime("%m/%d/%Y")
                self.time=self.datetime.strftime("%H:%M:%S")
                self.quoteTime = self.datetime.strftime("%Y%m%d%H%M%S") + '[' + YahooTimeZone + ']'
                self.pclose= '%.2f' % (quote['regularMarketPreviousClose']['raw'] * self.multiplier)

            except:
                #not formatted as expected?
                if Debug: log.debug('An error occured when parsing the Yahoo Finance response for %s' % self.ticker)
                self.status=False
        
class OfxWriter:
    """
    Create an OFX file based on a list of stocks and mutual funds.
    """
    
    def __init__(self, currency, account, shares, stockList, mfList):
        self.currency = currency
        self.account = account
        self.shares = shares
        self.stockList = stockList
        self.mfList = mfList
        self.dtasof = self.get_dtasof()

    def get_dtasof(self):
        #15-Feb-2011: Use the latest quote date/time for the statement
        today = datetime.now()
        dtasof   = today.strftime("%Y%m%d")+'120000'    #default to today @ noon     
        lastdate = datetime(1,1,1)                      #but compare actual dates to long, long ago...
        for ticker in self.stockList + self.mfList:
            if ticker.datetime > lastdate and not ticker.datetime > today:
                lastdate = ticker.datetime
                dtasof = ticker.quoteTime  
                
        return dtasof
        
    def _signOn(self):
        """Generate server signon response message"""
    
        return OfxTag("SIGNONMSGSRSV1",
                    OfxTag("SONRS",
                         OfxTag("STATUS",
                             OfxField("CODE", "0"),
                             OfxField("SEVERITY", "INFO"),
                             OfxField("MESSAGE","Successful Sign On")
                         ),
                         OfxField("DTSERVER", dateTimeStr()),
                         OfxField("LANGUAGE", "ENG"),
                         OfxField("DTPROFUP", "20010918083000"),
                         OfxTag("FI", OfxField("ORG", "PocketSense"))
                     )
               )

    def invPosList(self):
        # create INVPOSLIST section, including all stock and MF symbols
        posstock = []
        for stock in self.stockList:
            posstock.append(self._pos("stock", stock.symbol, stock.price, stock.quoteTime))

        posmf = []
        for mf in self.mfList:
            posmf.append(self._pos("mf", mf.symbol, mf.price, mf.quoteTime))
            
        return OfxTag("INVPOSLIST",          
                    join("", posstock),     #str.join("",StrList) = "str(0)+str(1)+str(2)..."
                    join("", posmf))


    def _pos(self, type, symbol, price, quoteTime):
        return OfxTag("POS" + type.upper(),
                   OfxTag("INVPOS",
                       OfxTag("SECID",
                           OfxField("UNIQUEID", symbol),
                           OfxField("UNIQUEIDTYPE", "TICKER")
                       ),
                       OfxField("HELDINACCT", "CASH"),
                       OfxField("POSTYPE", "LONG"),
                       OfxField("UNITS", str(self.shares)),
                       OfxField("UNITPRICE", price),
                       OfxField("MKTVAL", str(float2(price)*self.shares)),
                       #OfxField("MKTVAL", "0"),     #rlc:08-2013
                       OfxField("DTPRICEASOF", quoteTime)
                   )
               )

    def invStmt(self, acctid):
        #write the INVSTMTRS section
        stmt = OfxTag("INVSTMTRS",
                OfxField("DTASOF", self.dtasof),
                OfxField("CURDEF", self.currency),
                OfxTag("INVACCTFROM",
                    OfxField("BROKERID", "PocketSense"),
                    OfxField("ACCTID",acctid)
                ),
                OfxTag("INVTRANLIST",
                    OfxField("DTSTART", self.dtasof),
                    OfxField("DTEND", self.dtasof),
                ),
                self.invPosList()
               )

        return stmt

    def invServerMsg(self,stmt):
        #wrap stmt in INVSTMTMSGSRSV1 tag set
        s = OfxTag("INVSTMTTRNRS",
                    OfxField("TRNUID",ofxUUID()),
                    OfxTag("STATUS",
                        OfxField("CODE", "0"),
                        OfxField("SEVERITY", "INFO")),
                    OfxField("CLTCOOKIE","4"), 
                    stmt)
        return OfxTag("INVSTMTMSGSRSV1", s)
        
    def _secList(self):
        stockinfo = []
        for stock in self.stockList:
            stockinfo.append(self._info("stock", stock.symbol, stock.name, stock.price))

        mfinfo = []
        for mf in self.mfList:
            mfinfo.append(self._info("mf", mf.symbol, mf.name, mf.price))

        return OfxTag("SECLISTMSGSRSV1",
                   OfxTag("SECLIST",
                        join("", stockinfo),
                        join("", mfinfo)
                   )
               )

    def _info(self, type, symbol, name, price):
        secInfo = OfxTag("SECINFO",
                       OfxTag("SECID",
                           OfxField("UNIQUEID", symbol),
                           OfxField("UNIQUEIDTYPE", "TICKER")
                       ),
                       OfxField("SECNAME", name),
                       OfxField("TICKER", symbol),
                       OfxField("UNITPRICE", price),
                       OfxField("DTASOF", self.dtasof)
                   )
        if type.upper() == "MF":
            info = OfxTag(type.upper() + "INFO",
                       secInfo,
                       OfxField("MFTYPE", "OPENEND")
                   )
        else:
            info = OfxTag(type.upper() + "INFO", secInfo)

        return info
        
    def getOfxMsg(self):
        #create main OFX message block
        return join('', [OfxTag('OFX',
                        '<!--Created by PocketSense scripts for Money-->',
                        '<!--https://sites.google.com/site/pocketsense/home-->',
                        self._signOn(),
                        self.invServerMsg(self.invStmt(self.account)),
                        self._secList()
                    )])

    def writeFile(self, name):
        f = open(name,"w")
        f.write(OfxSGMLHeader())
        f.write(self.getOfxMsg())
        f.close()

def getYahooSession():
    #create requests session for yahoo finance
    #gets session cookie/crumb and reuses until it expires
    #deleting cookie file will force a refresh

    cookieFile='cookies.dat'
    yCookies, cookie, crumb=None, None, None

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.2; Win64; x64)'}
    if glob.glob(cookieFile):
        #read cookie info
        try:
            with open(cookieFile, 'rb') as f:
                data=pickle.load(f)
                yahooFin = data['yahooFinance']
                cookie = yahooFin['cookie']
                crumb  = yahooFin['crumb']
                expires = datetime.fromtimestamp(cookie.expires)
                if datetime.now() > (expires - timedelta(days=1)): 
                    cookie=None
        except Exception as e:
            log.debug('Error loading %s' % cookieFile)

    if not cookie:  
        #cookie not found or expiring soon.  refresh
        log.info('Fetching new Yahoo Finance cookie')
        response = requests.get("https://fc.yahoo.com", headers=headers, allow_redirects=True)
        if not response.cookies:
            log.error("Failed to obtain Yahoo auth cookie")
        else:
            yCookies=response.cookies   #requests cookiejar

        cookie = list(yCookies)[0]      #first cookie in cookiejar.  namespace type with all fields (i.e., cookie.name, cookie.value, etc.)
        expires = datetime.fromtimestamp(cookie.expires)

        crumb = None
        crumb_response = requests.get("https://query2.finance.yahoo.com/v1/test/getcrumb",
                headers=headers,
                cookies=yCookies,
                allow_redirects=True,
            )
        crumb = crumb_response.text
        if crumb is None:
            log.error("Failed to retrieve Yahoo crumb")

        #save cookie info
        cookieData = {'yahooFinance': {'cookie': cookie, 'crumb': crumb}}
        with open(cookieFile,'wb') as f:
            pickle.dump(cookieData, f)

    if Debug:
        log.debug('YahooFinance: cookie={cookie}, expires={expires}, crumb={crumb}'.format(
                    cookie=cookie, expires=expires.strftime('%m/%d/%Y'), crumb=crumb)
                 )
    session = requests.session()
    session.headers.update(headers)
    session.cookies.update({cookie.name: cookie.value})        
    return session, crumb

#----------------------------------------------------------------------------
def getQuotes():

    global YahooURL, eYahoo, GoogleURL, YahooTimeZone
    status = True    #overall status flag across all operations (true == no errors getting data)
    
    global log
    log = logging.getLogger('root')

    #get site and other user-defined data
    userdat = site_cfg.site_cfg()
    stocks = userdat.stocks
    funds = userdat.funds
    eYahoo = userdat.enableYahooFinance
    YahooURL = userdat.YahooURL
    YahooTimeZone = userdat.YahooTimeZone
    currency = userdat.quotecurrency
    account = userdat.quoteAccount
    ofxFile1, ofxFile2, htmFileName = '','',''

    #use single requests session for all
    global yahooSession, yahooCrumb
    yahooSession, yahooCrumb = getYahooSession()

    log.info('Getting security and fund quotes')
    stockList, mfList = [], []
    with yahooSession:
        for item in stocks:
            sec = Security(item)
            sec.getQuote()
            status = status and sec.status
            if sec.status: stockList.append(sec)
            
        for item in funds:
            sec = Security(item)
            sec.getQuote()
            status = status and sec.status
            if sec.status: mfList.append(sec)
        
    qList = stockList + mfList
    
    if len(qList) > 0:        #write results only if we have some data
        #create quotes ofx file  
        if not os.path.exists(xfrdir):
            os.mkdir(xfrdir)
        
        ofxFile1 = xfrdir + "quotes" + dateTimeStr() + str(random.randrange(1e5,1e6)) + ".ofx"
        writer = OfxWriter(currency, account, 0, stockList, mfList)
        writer.writeFile(ofxFile1)

        if userdat.forceQuotes:
           #generate a second file with non-zero shares.  Getdata and Setup use this file
           #to force quote reconciliation in Money, by sending ofxFile2, and then ofxFile1
           ofxFile2 = xfrdir + "quotes" + dateTimeStr() + str(random.randrange(1e5,1e6)) + ".ofx"
           writer = OfxWriter(currency, account, 0.001, stockList, mfList)
           writer.writeFile(ofxFile2)
        
        if glob.glob(ofxFile1) == []:
            status = False

        # write quotes.htm file
        htmFileName = QuoteHTMwriter(qList)
        
        #append results to QuoteHistory.csv if enabled
        if status and userdat.savequotehistory:
            csvFile = xfrdir+"QuoteHistory.csv"
            log.info('Appending quote results to {0}'.format(csvFile))
            newfile = (glob.glob(csvFile) == [])
            f = open(csvFile,"a")
            if newfile:
                f.write('Symbol,Name,Price,Date/Time,LastClose,%Change\n')
            for s in qList:
                #Fieldnames: symbol, name, price, quoteTime, pclose, pchange
                t = s.quoteTime
                t2 = t[4:6]+'/'+t[6:8]+'/'+t[0:4]+' '+ t[8:10]+":"+t[10:12]+":"+t[12:14]
                line = '"{0}","{1}",{2},{3},{4},{5}\n' \
                        .format(s.symbol, s.name, s.price, t2, s.pclose, s.pchange)
                f.write(line)
            f.close()
        
    return status, ofxFile1, ofxFile2, htmFileName