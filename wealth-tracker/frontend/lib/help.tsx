// What each screen is, and where its figures come from — in one place.
//
// Until now this was a paragraph at the top of every page: five to six lines of
// method above the first rule, read again every time by nobody. The text is not
// wrong, it is just permanently in the way of the figures you came for. Meridian
// says it plainly — information before decoration, every element earns its
// place — and an explanation you need once does not earn a fixed space on every
// visit.
//
// So: one "?" next to the page title in the top bar, always in the same place,
// that opens the dialog below. Three to five short paragraphs per screen: what
// you see, where it comes from, and what it is *not* about. Everything shorter
// than that which belongs to one section or one number does not go here but
// behind the "i" on that section itself.
//
// The key is the path. Exact first, then the longest path that is a prefix of it
// — that way an unknown sub-address inherits the help of the screen it belongs
// to without every ISIN needing a row of its own. A key ending in "/*" applies
// *only* to those sub-addresses: /portfolio is the list, /portfolio/* is one
// position, and those are two screens.

import Link from "next/link";
import { tr, trx } from "@/lib/i18n";

/** To a chapter of Help → Money. */
function Explanation({ anchor, children }: { anchor: string; children: React.ReactNode }) {
  return <Link href={`/help/money#${anchor}`} className="underline underline-offset-4">{children}</Link>;
}

export type PageHelp = {
  /** The heading of the dialog. Sentence case, no capitals. */
  title: string;
  body: React.ReactNode;
};

/** One paragraph in a help dialog. */
function P({ children }: { children: React.ReactNode }) {
  return <p>{children}</p>;
}

/**
 * A subheading in a longer help dialog, for the screen that has three subjects in
 *  it instead of one.
 */
function H({ children }: { children: React.ReactNode }) {
  return <h3 className="ds-eyebrow mt-1.5 block">{children}</h3>;
}

const HELP: Record<string, PageHelp> = {
  "/dashboard": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("What your portfolio is worth today, and how that value came about. The big number at the top is the sum of all your positions at their last fetched price.")}</P>
        <P>{tr("Prices come from Yahoo Finance and run about a quarter of an hour behind the exchange. They are refreshed as soon as you come in and further when you click Update. If it says “not current” next to the day result, that number is about the last day for which there are prices, not about today.")}</P>
        <P>{tr("Every short number is next to a long number. The day result never appears alone: it's next to the total value and next to what you've earned since you started. A day says little, and the screen is built so you can't read that day on its own.")}</P>
        <P>{tr("“What deserves your attention” is the only place that asks something of you, and usually it asks nothing. Nothing is added that doesn't really matter.")}</P>
      </>
    ),
  },

  "/portfolio": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Every position you own now, with what it's worth and what it has yielded you. The same ISIN on two exchanges is two positions at DeGiro, each with its own average purchase price, and so it is two rows here as well.")}</P>
        <H>{tr("The three result numbers")}</H>
        <P>{trx("{0} is the average purchase price per unit, excluding transaction costs, so it can be put directly next to the price.", <b>{tr("Avg cost")}</b>)}</P>
        <P>{trx("{0} measures the current price against that average cost: gain on paper.", <b>{tr("Unrealised")}</b>)}</P>
        <P>{trx("{0} is what the position yielded you in total: the unrealised result plus earlier realised gain and received dividend, minus all transaction costs, over everything you ever put in.", <b>{tr("Total P/L")}</b>)}</P>
        <P>{trx("Click a position for its price chart and the full breakdown. The {0} tab puts the raw prices and the fetch moment next to it.", <b>{tr("Details")}</b>)}</P>
      </>
    ),
  },

  "/portefeuille/*": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("One position: what the product itself did, and what your units of it have yielded. Those are two different things, and so they are shown one below the other instead of mixed together.")}</P>
        <P>{trx("The chart is the {0}. Your purchases, your quantities and your received dividend aren't in it: that line would look the same for everyone who owns this fund. Drag over the line, or put two fingers on it, to compare two moments.", <b>{tr("price of the product")}</b>)}</P>
        <H>{tr("The numbers below it")}</H>
        <P>{trx("{0} is your average purchase price per unit, excluding transaction costs, so it can be put next to the price. {1} does include costs: that's what really left your account.", <b>{tr("Avg cost")}</b>, <b>{tr("Deposited")}</b>)}</P>
        <P>{trx("{0} measures the current price against that average cost. {1} adds earlier realised gain and received dividend to it and deducts all transaction costs. The breakdown next to it shows how the two relate.", <b>{tr("Unrealised")}</b>, <b>{tr("Total P/L")}</b>)}</P>
        <P>{tr("The same ISIN on a second exchange is a separate position at DeGiro with its own average cost, and so it is a separate screen here.")}</P>
        <H>{tr("What's in it")}</H>
        <P>{tr("For a tracker the bottom shows what the fund itself owns: the largest companies, the sectors and the countries. That comes from the file the fund provider publishes, the same source the Allocation tab is made from, here for this one fund instead of your whole portfolio.")}</P>
        <P>{tr("The bars are against the whole fund. In a fund of five hundred companies the largest item is therefore a sliver, and in a sector fund that same name fills a fifth of the bar. That difference is the answer to how diversified the fund is.")}</P>
      </>
    ),
  },

  "/details": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Exactly the prices behind every number on Today, with the moment each was fetched. Comparable row by row with DeGiro, so you see where a difference in total value comes from.")}</P>
        <P>{tr("A difference of cents per position is normal: Yahoo runs about a quarter of an hour behind and may quote a different exchange than the one you bought on.")}</P>
        <P>{trx("If a price is really wrong, usually the wrong listing was chosen. Click the ticker and enter the right one from finance.yahoo.com, for example {0} for XETRA or {1} for Amsterdam. The price is then fetched again from there.", <code>IQQH.DE</code>, <code>VUSA.AS</code>)}</P>
        <P>{tr("Further, all your transactions are here, all received dividends and the positions you have since sold completely: the full log behind the rest of the app.")}</P>
      </>
    ),
  },

  "/returns": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Two ways to judge the same period. They often give a different answer and both are right, because they measure something different. Each number has an “i” with when to use it.")}</P>
        <H>{tr("Which number do I need?")}</H>
        <P>{trx("{0} Time-weighted. Put it next to the MSCI World on the Benchmarks tab: that one uses the same method.", <b>{tr("“Am I doing better than the market?”")}</b>)}</P>
        <P>{trx("{0} The amount in euros on Today. That's the only number you can actually withdraw.", <b>{tr("“How much have I earned?”")}</b>)}</P>
        <P>{trx("{0} Money-weighted. If it's higher than the time-weighted, you deposited at good moments on average; if it's lower, you more often deposited just before a fall.", <b>{tr("“Was it smart to get in then?”")}</b>)}</P>
        <P>{trx("{0} Because your portfolio used to be small and is large now. A good year when you had €500 invested counts as heavily time-weighted as a mediocre year with €13,000, but not in your wallet.", <b>{tr("“Why do they differ so much?”")}</b>)}</P>
      </>
    ),
  },

  "/benchmarks": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Your own return next to that of the big indices, based on total return: so including dividend.")}</P>
        <P>{tr("For your own portfolio the time-weighted return is used, so a deposit doesn't count as gain. The indices use the same method; that's what makes the comparison fair.")}</P>
        <P>{tr("The S&P 500 (SPY) and EURO STOXX 50 (FEZ) are quoted in dollars and converted to euros at the daily rate. Prices come from Yahoo Finance and are kept for an hour.")}</P>
        <P>{tr("Bonds are left out by default. Bond funds behave like savings, and counting them makes an equity portfolio look slower than it is next to an equity index. The tick box above the charts brings them back.")}</P>
      </>
    ),
  },

  "/allocation": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Where your money really is, looked through into the funds, not just to the ETF. Every company in one of your funds counts here for the part you own of it.")}</P>
        <P>{tr("The figures come from the complete holdings files the providers publish themselves (iShares, SPDR, Vanguard), with a sector and country label per position. Funds that don't publish that machine-readably fall back to an index proxy or an estimate from Yahoo or justetf. Under “How solid are these figures?” each fund shows which source it is. Holdings are kept locally for 7 days.")}</P>
        <P>{tr("Bond funds don't count: sector and country data only say something about shares. So all percentages on this screen are about your equity part.")}</P>
        <P>{tr("Country means the company's country of listing, not where it earns its revenue. A Dutch company that earns nearly everything in Asia is shown here under the Netherlands.")}</P>
      </>
    ),
  },

  "/rebalancing": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Where your portfolio stands against your target allocation, and how your next deposit closes that gap fastest.")}</P>
        <P>{tr("You set two targets. The first is the ratio of shares to bonds; the other side is calculated automatically, so it always adds up to 100%. The second is the split over the US, Europe and emerging markets within your shares.")}</P>
        <P>{tr("For the first classification we guess per position based on the name. You correct what goes wrong yourself under “Classify your positions”; that choice is saved.")}</P>
        <P>{tr("You don't need to tag the market split. It comes from the same looked-through holdings as the country breakdown on Allocation: every equity position (inside your ETF’s and individual) is classified by country of listing and added up to the three markets.")}</P>
        <P>{tr("What we suggest is arithmetic, not advice: it's the split of your amount that narrows the difference with your target fastest. Selling is never suggested.")}</P>
      </>
    ),
  },

  "/dividend": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Everything your funds actually paid out, and what is still coming according to their own rhythm. Amounts are net, after withheld dividend tax.")}</P>
        <P>{trx("The number at the top is about a {0} year and not the calendar year, because in January a calendar year is three days long. Every percentage on this screen about “a year” is measured over that window.", <b>{tr("rolling")}</b>)}</P>
        <H>{tr("What an estimate is, and what it isn't")}</H>
        <P>{trx("An amount with {0} in front is an expectation, derived from your own payout history: the rhythm and the usual amount, extended. Not an official announcement. That's why there is a month and a part of the month and no date: the rhythm is known, the day isn't.", <b>±</b>)}</P>
        <P>{tr("A row with “official” does come from an announced ex-dividend date. Funds without a recognisable rhythm (fewer than two payouts, or an erratic pattern) are left out, not guessed.")}</P>
        <P>{tr("If none of your funds pays out, you're not missing anything: an accumulating ETF reinvests the dividends itself, and that gain is already in the price.")}</P>
      </>
    ),
  },

  "/calendar": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("When something happens with your positions: when a company publishes its results, when you lock in the right to a dividend (the ex-dividend date), and when money actually came into your account.")}</P>
        <H>{tr("Why not everything is in a box")}</H>
        <P>{trx("A box in the grid means the date {0}: it has happened, or the source gives it itself. Expected payouts are therefore not in the grid but in the strip below: those are derived from your own payout history, and that rhythm is known to the month and not to the day.", <b>{tr("is fixed")}</b>)}</P>
        <P>{trx("The calendar knows nothing of a {0}: Yahoo has no announced dates for a UCITS tracker, and a fund doesn't publish quarterly results of its own anyway; the companies it invests in do. If you only own funds, the strip fills this page and the grid stays mostly empty. That's not a fault.", <b>{tr("fund")}</b>)}</P>
        <H>{tr("The report with it")}</H>
        <P>{tr("A publication date that has passed has a way to the document itself. For an American share that's a direct link to the filed quarterly or annual report at the SEC. For the rest such a source doesn't exist yet. The European counterpart, ESAP, only opens in July 2027, so the best there is is a link to the company's website.")}</P>
      </>
    ),
  },

  "/news": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("News about what you actually own. The feeds are put together from your own positions: first your individual shares, then the largest companies within your ETF’s, then the broader market news.")}</P>
        <P>{tr("Articles come from Finnhub and Alpha Vantage. We don't write them and don't judge them: the label next to it (quarterly results, takeover) only says what the article is about.")}</P>
        <P>{tr("Nothing appears in red, nothing is counted and there's no order that suggests urgency. News is context for your portfolio, not a reason to do something.")}</P>
      </>
    ),
  },

  "/net-worth": {
    title: tr("Net worth"),
    body: (
      <>
        <P>{tr("Your investments plus bank and cash, minus your debts, for every day. Investments is your portfolio from this app plus the cash balance at DeGiro and other brokers.")}</P>
        <P>{tr("Balances come from your bank connection, your exports and what you enter yourself; between two measurements the app calculates with your transactions. An account without a single balance doesn't count: unknown is not zero.")}</P>
        <P>{trx("More about how balances and net worth come about: {0}.", <Explanation anchor="balances">{tr("Balances and net worth")}</Explanation>)}</P>
      </>
    ),
  },
  "/accounts": {
    title: tr("Accounts"),
    body: (
      <>
        <P>{tr("All your accounts, grouped as they count in your net worth, with their last known balance and its date. The app creates accounts from an export or connection itself; cash, a broker or a debt you add here.")}</P>
        <P>{trx("One balance per account is enough. How to get your data in: {0}.", <Explanation anchor="importing">{tr("Getting your data in")}</Explanation>)}</P>
      </>
    ),
  },
  "/spending": {
    title: tr("Spending"),
    body: (
      <>
        <P>{tr("Where your money went, per period, account and category. Internal (money between your own accounts, gifts, other people's money) doesn't count as income or expense.")}</P>
        <P>{trx("If something is wrong, set the right category; with “Make rule” it applies to that counterparty from then on. {0}.", <Explanation anchor="labelling">{tr("How labelling works")}</Explanation>)}</P>
      </>
    ),
  },
  "/categories": {
    title: tr("Categories"),
    body: (
      <>
        <P>{tr("Your categories and the rules that fill them. You label transactions at Transactions (a selection or one transaction) and at To label (what has no category yet or looks wrong). A category you set by hand always wins.")}</P>
        <P>{trx("What each category does with your income, spending and net worth: {0}.", <Explanation anchor="special-cases">{tr("Categories that count differently")}</Explanation>)}</P>
      </>
    ),
  },
  "/help": {
    title: "Help",
    body: (
      <>
        <P>{tr("The explanation of both parts of the app in one place. Getting started shows what you've already done and what's still possible; Portfolio and Money are the guides, with the same structure.")}</P>
        <P>{tr("Here you also choose what you keep track of, and restart the first-time tour.")}</P>
      </>
    ),
  },
  "/account": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Your own account. If you change your password here, all your other sessions are logged out: that's intended, so a session on a device you've lost doesn't stay in.")}</P>
        <P>{tr("Your data is in your own database, separate from that of other users. We sell nothing on and there isn't a single external tracker in this app.")}</P>
      </>
    ),
  },

  "/admin": {
    title: tr("About this screen"),
    body: (
      <>
        <P>{tr("Accounts, sign-up, feedback and beta features of this tracker. Only visible to admins, and the API checks that again on every request: a hidden link is not a lock.")}</P>
        <P>{tr("Tick several accounts to do the same for all of them at once. With a trackerai.nl front door, the admin link goes to trackerai.nl/admin: the same page for every tracker.")}</P>
      </>
    ),
  },
};

/**
 * The help that belongs to this address.
 *
 * Exact first, then the longest path that is a prefix of this address: the detail
 * page of a position thus inherits the help of Portfolio without every ISIN
 * needing a row here. No match means no "?" in the bar — a button that opens an
 * empty dialog is worse than no button.
 */
export function helpFor(pathname: string): PageHelp | null {
  if (HELP[pathname]) return HELP[pathname];
  const key = Object.keys(HELP)
    .filter((p) => {
      const agree = p.endsWith("/*") ? p.slice(0, -2) : p;
      return pathname.startsWith(`${agree}/`);
    })
    // Het langste eerst, zodat "/portefeuille/*" wint van "/portefeuille" op een
    // adres waar allebei op passen.
    .sort((a, b) => b.length - a.length)[0];
  return key ? HELP[key] : null;
}
