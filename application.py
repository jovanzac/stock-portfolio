import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    symbols = [data["Symbol"] for data in db.execute("SELECT Symbol FROM holdings WHERE holdings.user_id=?", session["user_id"])]
    names = [lookup(symbol)["name"] for symbol in symbols]
    shares = list()
    for symbol in symbols:
        shares += [db.execute("SELECT Shares FROM holdings WHERE holdings.user_id=? AND Symbol=?",
                              session["user_id"], symbol)[0]["Shares"]]
    cur_price = [lookup(symbol)["price"] for symbol in symbols]
    holding_value = [round(float(shares[i]*cur_price[i]), 2) for i in range(len(cur_price))]

    # Sum total of current stock values in possession of the user
    total = round(float(sum(holding_value) + session["balance"]), 2)

    return render_template("home.html", symbols=symbols, names=names, shares=shares,
                           cur_price=[usd(price) for price in cur_price], holding_value=[usd(price) for price in holding_value], table_len=len(symbols),
                           balance=usd(round(float(session["balance"]), 2)), total=usd(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        symbol = request.form.get("symbol")

        try:
            shares = int(request.form.get("shares"))
        except ValueError:
            return apology("Shares must be positive integers", 400)

        if not shares:
            return apology("Shares field cannot be left empty", 400)

        if shares < 1:
            return apology("Invalid shares chosen", 400)

        # Check whether the symbol field is empty or the symbol exists
        if not symbol or not lookup(symbol):
            return apology("Sorry, Symbol not recognised", 400)

        # Check whether user has enough money for the requested purchase
        if (lookup(symbol)["price"] * shares) > session["balance"]:
            return apology("Sorry, but you dont have enough money for this purchase", 400)

        # Insert the values for this transaction into the table, transactions
        db.execute("INSERT INTO transactions (user_id, Symbol, Shares, Price) VALUES (?, ?, ?, ?)",
                   session["user_id"], symbol, shares, lookup(symbol)["price"])

        # Update the table, holdings, in the database and the session
        if symbol in session["stock"]:
            session["stock"][symbol] += shares
            db.execute("UPDATE holdings SET Shares=? WHERE user_id=? AND Symbol=?",
                       session["stock"][symbol], session["user_id"], symbol)

        else:
            session["stock"][symbol] = shares
            db.execute("INSERT INTO holdings (user_id, Symbol, Shares) VALUES (?, ?, ?)", session["user_id"], symbol, shares)

        # Find out how much money the user will have left once the purchase has been completed and update the database accordingly
        session["balance"] -= round(float(shares * lookup(symbol)["price"]), 2)
        db.execute("UPDATE users SET cash=?", session["balance"])

        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    rows = db.execute(
        "SELECT Symbol, Shares, Price, Time FROM transactions WHERE transactions.user_id=? ORDER BY transactions.Time", session["user_id"])

    return render_template("history.html", data=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        username = request.form.get("username")
        psswd = request.form.get("password")

        # Ensure username was submitted
        if not username:
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not psswd:
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username=?", username)

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], psswd):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        # Keep track of the users balance
        session["balance"] = round(float(rows[0]["cash"]), 2)
        # Keep track of all the stock the user owns
        session["stock"] = {data["Symbol"]: int(data["Shares"]) for data in db.execute(
            "SELECT Symbol, Shares FROM holdings WHERE holdings.user_id=?", session["user_id"])}

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        # If symbol field is empty return an apology
        if not symbol:
            return apology("Symbol field cannot be left empty", 400)

        # Get the quote for the specified company using the lookup function from helpers.py
        quote_dict = lookup(symbol)
        # Check whether lookup was able to find the quote for the requested symbol
        if not quote_dict:
            return apology(f"Sorry, nothing found for {symbol}", 400)

        return render_template("quoted.html", name=quote_dict["name"], price=usd(quote_dict["price"]), symbol=symbol)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        # Check whether the username space is empty
        if not username:
            return apology("Username Required", 400)

        # Check whether either of the the password spaces are empty
        if not password or not confirmation:
            return apology("Both Password Spaces Required to Be Filled", 400)

        # Check whether the confirmation is same as the initially typed password
        if password != confirmation:
            return apology("Confirmation is not the same as the initially entered password", 400)

        rows = db.execute("SELECT * FROM users WHERE username=?", username)

        # Check whether the entered username already exists
        if len(rows) > 0:
            return apology("Sorry, username already exists", 400)

        # If no problems then insert the new user into the database
        psswd_hash = generate_password_hash(password)
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, psswd_hash)

        data = db.execute("SELECT id, cash FROM users WHERE username=?", username)

        session["user_id"] = data[0]["id"]
        # Keep track of the users balance amount
        session["balance"] = data[0]["cash"]
        # Keep track of all the stock the user owns
        session["stock"] = {data["Symbol"]: int(data["Shares"]) for data in db.execute(
            "SELECT Symbol, Shares FROM holdings WHERE holdings.user_id=?", session["user_id"])}

        # Redirect user to homepage
        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        try:
            shares = int(request.form.get("shares")) * -1
        except (TypeError, ValueError):
            return apology("The shares field must not be left empty", 400)

        if shares >= 0:
            return apology("Invalid number of shares chosen", 400)

        if shares * -1 > session["stock"][symbol]:
            return apology("You are attempting to sell more shares than you own", 400)

        if not symbol:
            return apology("The symbol field must not be left empty", 400)

        # Update the transactions database
        db.execute("INSERT INTO transactions (user_id, Symbol, Shares, Price) VALUES (?, ?, ?, ?)",
                   session["user_id"], symbol, shares, lookup(symbol)["price"])
        # Update session data
        session["stock"][symbol] += shares
        # Update the holdings database
        db.execute("UPDATE holdings SET Shares=? WHERE user_id=? AND Symbol=?",
                   session["stock"][symbol], session["user_id"], symbol)
        # Update the amount the user has left in account after sales
        session["balance"] += shares * lookup(symbol)["price"] * -1
        db.execute("UPDATE users SET cash=? WHERE id=?", session["balance"], session["user_id"])

        return redirect("/")

    else:
        symbols = list(symbol for symbol in session["stock"])

        return render_template("sell.html", symbols=symbols)


@app.route("/cash", methods=["GET", "POST"])
@login_required
def cash():
    if request.method == "POST":
        try:
            cash = int(request.form.get("cash"))

        except (TypeError, ValueError):
            return apology("Invalid amount", 400)

        # Update the cash in the database
        session["balance"] += cash
        db.execute("UPDATE users SET cash=? WHERE id=?", session["balance"], session["user_id"])

        return redirect("/")

    else:
        return render_template("cash.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
