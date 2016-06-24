# -*- coding: utf-8 -*-`
"""api.py - Create and configure the Game API exposing the resources.
This can also contain game logic. For more complex games it would be wise to
move game logic to another file. Ideally the API will be simple, concerned
primarily with communication to/from the API's users."""


import logging
import endpoints
from protorpc import remote, messages
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from models import User, Game, Score
from models import StringMessage, NewGameForm, GameForm, MakeMoveForm,\
    ScoreForms, GameForms, GetHighScoresForm, HighScoresForm, HighScoresForms,\
    Move, HistoryForm
from utils import get_by_urlsafe

NEW_GAME_REQUEST = endpoints.ResourceContainer(NewGameForm)
GET_GAME_REQUEST = endpoints.ResourceContainer(
        urlsafe_game_key=messages.StringField(1),)
MAKE_MOVE_REQUEST = endpoints.ResourceContainer(
    MakeMoveForm,
    urlsafe_game_key=messages.StringField(1),)
USER_REQUEST = endpoints.ResourceContainer(user_name=messages.StringField(1),
                                           email=messages.StringField(2))

MEMCACHE_MOVES_REMAINING = 'MOVES_REMAINING'

HIGH_SCORES_REQUEST = endpoints.ResourceContainer( number_of_results = messages.IntegerField(1, required=True))

#endpoints.ResourceContainer(GetHighScoresForm)

@endpoints.api(name='hangman', version='v0.1')
class HangmanApi(remote.Service):
    """Game API"""

    @endpoints.method(request_message=USER_REQUEST,
                      response_message= GameForms,
                      path='games/user/{user_name}',
                      name='get_user_games',
                      http_method='GET')
    def get_user_games(self, request):
        """Get a user's games"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        games = Game.query(Game.user == user.key)
        return GameForms(items=[game.to_form("") for game in games])


    @endpoints.method(response_message=HighScoresForms,
                    path='scores/rankings',
                    name='get_user_rankings',
                    http_method='GET')
    def get_user_rankings(self, request):
        """Get all players ranked by performance"""
        users = User.query()
        scores = []

        for user in users:
            score = self.get_user_score(user)
            scores.append(HighScoresForm(user_name=user.name, score=score))

        return HighScoresForms(highScores = scores)


    @endpoints.method(request_message=GET_GAME_REQUEST,
                    response_message= StringMessage,
                    path = 'game/{urlsafe_game_key}/cancel',
                    name='cancel_game',
                    http_method='POST')
    def cancel_game(self, request):
        """Cancel an active game"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)

        if game:
            if game.game_over == False:
                game.game_over = True
                game.attempts_remaining = 0
                game.put()
                return StringMessage(message="Game cancelled!")
            else:
                raise endpoints.BadRequestException('You cannot cancel a finished game.')
        else:
            raise endpoints.NotFoundException('Game not found!')

    def get_user_score(self, user):
        scores = Score.query(Score.user == user.key)
        total = 0

        for score in scores:
            if(score.won == "Ture"):
                total += 1
            else:
                total -= 1

        return total


    @endpoints.method(request_message=HIGH_SCORES_REQUEST,
                      response_message=HighScoresForms,
                      path='scores/highscores',
                      name='get_high_scores',
                      http_method='GET')
    def get_high_scores(self, request):
        """Get the high scores"""

        users = User.query()
        scores = []

        for user in users:
            score = self.get_user_score(user)
            scores.append(HighScoresForm(user_name=user.name, score=score))

        # Sorting the scores
        for i in range(0, len(scores)):
            for j in range(1,len(scores)):
                if scores[i].score < scores[j].score:
                    temp = scores[i]
                    scores[i] = scores[j]
                    scores[j] = temp
        return HighScoresForms(highScores = scores[0:request.number_of_results])


    @endpoints.method(request_message=GET_GAME_REQUEST,
                    response_message=HistoryForm,
                    path="game/{urlsafe_game_key}/history",
                    name='get_game_history',
                    http_method='GET')
    def get_game_history(self, request):
        """Get the history of a game"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)

        history = []

        if game:
            for letter in game.history:
                if letter in game.target:
                    history.append(Move(move = letter, outcome="Good guess!"))
                else:
                    history.append(Move(move = letter, outcome="Bad guess!"))
            return HistoryForm(moves = history)
        else:
            raise endpoints.NotFoundException('Game not found!')

    @endpoints.method(request_message=USER_REQUEST,
                      response_message=StringMessage,
                      path='user',
                      name='create_user',
                      http_method='POST')
    def create_user(self, request):
        """Create a User. Requires a unique username"""
        if User.query(User.name == request.user_name).get():
            raise endpoints.ConflictException(
                    'A User with that name already exists!')
        user = User(name=request.user_name, email=request.email)
        user.put()
        return StringMessage(message='User {} created!'.format(
                request.user_name))

    @endpoints.method(request_message=NEW_GAME_REQUEST,
                      response_message=GameForm,
                      path='game',
                      name='new_game',
                      http_method='POST')
    def new_game(self, request):
        """Creates new game"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        
        game = Game.new_game(user.key, request.attempts)

        # Use a task queue to update the average attempts remaining.
        # This operation is not needed to complete the creation of a new game
        # so it is performed out of sequence.
        taskqueue.add(url='/tasks/cache_average_attempts')
        return game.to_form('Good luck playing Hangman!')

    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='get_game',
                      http_method='GET')
    def get_game(self, request):
        """Return the current game state."""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game:
            return game.to_form('Time to make a move!')
        else:
            raise endpoints.NotFoundException('Game not found!')

    @endpoints.method(request_message=MAKE_MOVE_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='make_move',
                      http_method='PUT')
    def make_move(self, request):
        """Makes a move. Returns a game state with message"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game.game_over:
            return game.to_form('Game already over!')

        if len(request.guess) != 1 or not request.guess[0].isalpha():
            return game.to_form('Guess must be a letter!')

        game.attempts_remaining -= 1

        if request.guess[0] in game.history:
            return game.to_form('You already guessed that letter!')
        else:
            game.history = game.history + request.guess[0]

        if request.guess[0] in game.target:
            good_guess = True
        else:
            good_guess = False

        prog = ""

        for index in range(0,len(game.progress)):
            if request.guess[0] == game.target[index]:
                prog += game.target[index]
            else:
                prog += game.progress[index]

        game.progress = prog.encode("utf-8")

        
                
        if game.progress == game.target:
            game.end_game(True)
            return game.to_form('You win!')

        if good_guess:
            msg = 'Good guess!'
        else:
            msg = 'Bad guess!'

        if game.attempts_remaining < 1:
            game.end_game(False)
            return game.to_form(msg + ' Game over!')
        else:
            game.put()
            return game.to_form(msg)

    @endpoints.method(response_message=ScoreForms,
                      path='scores',
                      name='get_scores',
                      http_method='GET')
    def get_scores(self, request):
        """Return all scores"""
        return ScoreForms(items=[score.to_form() for score in Score.query()])

    @endpoints.method(request_message=USER_REQUEST,
                      response_message=ScoreForms,
                      path='scores/user/{user_name}',
                      name='get_user_scores',
                      http_method='GET')
    def get_user_scores(self, request):
        """Returns all of an individual User's scores"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        scores = Score.query(Score.user == user.key)
        return ScoreForms(items=[score.to_form() for score in scores])

    @endpoints.method(response_message=StringMessage,
                      path='games/average_attempts',
                      name='get_average_attempts_remaining',
                      http_method='GET')
    def get_average_attempts(self, request):
        """Get the cached average moves remaining"""
        return StringMessage(message=memcache.get(MEMCACHE_MOVES_REMAINING) or '')

    @staticmethod
    def _cache_average_attempts():
        """Populates memcache with the average moves remaining of Games"""
        games = Game.query(Game.game_over == False).fetch()
        if games:
            count = len(games)
            total_attempts_remaining = sum([game.attempts_remaining
                                        for game in games])
            average = float(total_attempts_remaining)/count
            memcache.set(MEMCACHE_MOVES_REMAINING,
                         'The average moves remaining is {:.2f}'.format(average))


api = endpoints.api_server([HangmanApi])
