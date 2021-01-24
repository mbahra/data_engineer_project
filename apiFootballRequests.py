import requests
import datetime
import json
import csv
import schedule
import time
import logging
import boto3
import uuid
import io
import pandas as pd
from botocore.exceptions import ClientError

def fixturesRequest(startDate, endDate):
    """
    Sends a request to API Football to get the 2020/2021 english Premier League fixtures
    from a starting date to an ending date, then returns the response without a json object.
    """

    url = "https://api-football-beta.p.rapidapi.com/fixtures"
    headers = {
    'x-rapidapi-key': "XXX", # Replace XXX by your API key
    'x-rapidapi-host': "api-football-beta.p.rapidapi.com"
    }
    querystring = {"league":"39", "season":"2020", "from":startDate, "to":endDate}
    response = requests.request("GET", url, headers=headers, params=querystring)
    return response.json()

def uploadJsonToS3(jsonObject, bucket, s3Connection, prefix, name):
    """
    Uploads json object to S3 by encoding it in utf-8.
    """

    data = json.dumps(jsonObject).encode('UTF-8')
    # The key has a uuid prefix to avoid partition issue
    key = ''.join([prefix, str(uuid.uuid4().hex[:6]), '-', name])
    s3Connection.put_object(Body=data, Bucket=bucket, Key=key)
    print(key + ' uploaded into ' + bucket)

def uploadCsvToS3(df, bucket, s3Connection, prefix, name):
    """
    Converts a dataframe to a csv,
    then uploads the csv file directly to S3 without storing it locally.
    """

    csvBuffer = io.StringIO()
    df.to_csv(csvBuffer)
    # The key has a uuid prefix to avoid partition issue
    key = ''.join([prefix, str(uuid.uuid4().hex[:6]), '-', name])
    s3Connection.put_object(Body=csvBuffer.getvalue(), Bucket=bucket, Key=key)
    print(key + ' uploaded into ' + bucket)

def uploadFixturesCsvToS3(data, bucket, s3Connection, prefix, name):
    """
    Converts a fixture json file to a dataframe containing the relevant data.
    Converts the dataframe to a csv.
    Uploads the csv file directly to S3 without storing it locally.
    Returns the dataframe.
    """

    # Get teamcodes from S3 to construct hashtags
    teamcodes = s3Connection.get_object(Bucket=bucket, Key='processed-data/teamcodes.csv')
    teamcodesDf = pd.read_csv(teamcodes['Body'])
    # Process the json object's data to a dataframe
    df = pd.DataFrame(columns=['idFixture', 'status', 'date', 'time', 'hashtag',
                                    'idHomeTeam', 'idAwayTeam', 'goalsHomeTeam', 'goalsAwayTeam'])
    for fixture in data['response']:
        idFixture = fixture['fixture']['id']
        status = fixture['fixture']['status']['long']
        date = fixture['fixture']['date'][:10]
        time = fixture['fixture']['date'][11:16]
        idHomeTeam = fixture['teams']['home']['id']
        idAwayTeam = fixture['teams']['away']['id']
        teamcodeHomeTeam = teamcodesDf.loc[teamcodesDf['idTeam'] == idHomeTeam]['teamCode'].item()
        teamcodeAwayTeam = teamcodesDf.loc[teamcodesDf['idTeam'] == idAwayTeam]['teamCode'].item()
        hashtag = ''.join(['#', teamcodeHomeTeam, teamcodeAwayTeam])
        goalsHomeTeam = fixture['goals']['home']
        goalsAwayTeam = fixture['goals']['away']
        row = {'idFixture':idFixture, 'status':status, 'date':date, 'time':time, 'hashtag':hashtag,
                'idHomeTeam':idHomeTeam, 'idAwayTeam':idAwayTeam,
                'goalsHomeTeam':goalsHomeTeam, 'goalsAwayTeam':goalsAwayTeam}
        df = df.append(row, ignore_index=True)
    # Convert df to csv and upload it to S3 into the 'processed-data' folder
    uploadCsvToS3(df, bucket, s3Connection, prefix, name)

def main():

    s3_client = boto3.client('s3')

    dataLakeBucketName = '' # Replace XXX by your bucket name

    # Run each of these tasks weekly:
    # Get every previous week fixtures, their statistics, and the next week fixtures from API Football
    # Upload the json objects to the datalake into the 'raw-data' folder
    # Process each json response received to a dataframe
    # Convert each dataframe to csv
    # Upload csv directly to the datalake into the 'processed-data' folder

    previousWeekDate = (datetime.datetime.today() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
    yesterdayDate = (datetime.datetime.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    todayDate = datetime.datetime.today().strftime('%Y-%m-%d')
    nextWeekDate = (datetime.datetime.today() + datetime.timedelta(days=6)).strftime('%Y-%m-%d')

    # NEXT WEEK FIXTURES
    # Get next week fixtures from API Football
    nextWeekFixturesJson = fixturesRequest(todayDate, nextWeekDate)
    # Upload next week fixtures json object into 'raw-data' folder
    prefix = 'raw-data/api-football/nextFixtures/'
    name = ''.join(['nextWeekFixtures-', todayDate, '.json'])
    uploadJsonToS3(nextWeekFixturesJson, dataLakeBucketName, s3_client, prefix, name)
    # Process and upload next week fixtures as a csv file into 'processed-data' folder
    prefix = 'processed-data/api-football/nextFixtures/'
    name = ''.join(['nextWeekFixtures-', todayDate, '.csv'])
    uploadFixturesCsvToS3(nextWeekFixturesJson, dataLakeBucketName, s3_client, prefix, name)

    # PREVIOUS WEEK FIXTURES
    # Get previous week fixtures from API Football
    previousWeekFixturesJson = fixturesRequest(previousWeekDate, yesterdayDate)
    # Upload previous week fixtures json object into 'raw-data' folder
    prefix = 'raw-data/api-football/previousFixtures/'
    name = ''.join(['previousWeekFixtures-', todayDate, '.json'])
    uploadJsonToS3(previousFixturesJson, dataLakeBucketName, s3_client, prefix, name)
    # Process and upload previous week fixtures as a csv file into 'processed-data' folder
    prefix = 'processed-data/api-football/previousFixtures/'
    name = ''.join(['previousWeekFixtures-', todayDate, '.csv'])
    uploadFixturesCsvToS3(previousFixturesJson, dataLakeBucketName, s3_client, prefix, name)

    # STATISTICS
    # Create dataframe columns for statistcs data
    df = pd.DataFrame(columns=['idFixture', 'idHomeTeam', 'idAwayTeam',
                                'shotsOnGoalHomeTeam', 'shotsOnGoalAwayTeam',
                                'shotsInsideBoxHomeTeam', 'shotsInsideBoxAwayTeam',
                                'totalShotsHomeTeam', 'totalShotsAwayTeam',
                                'ballPossessionHomeTeam', 'ballPossessionAwayTeam'])
    # Get statistics for each previous fixtures from API Football
    for fixture in previousWeekFixturesJson['response']:
        status = fixture['fixture']['status']['long']
        if status == 'Match Postponed':
            continue
        idFixture = fixture['fixture']['id']
        statisticsJson = statisticsRequest(idFixture)
    # Upload statistics json object into 'raw-data' folder
        prefix = 'raw-data/statistics/'
        name = ''.join(['statistics-', str(idFixture), '.json'])
        uploadJsonToS3(statisticsJson, dataLakeBucketName, s3_client, prefix, name)
    # Process each statistics json data to a new dataframe row
        homeTeam = statisticsJson['response'][0]
        awayTeam = statisticsJson['response'][1]
        idHomeTeam = homeTeam['team']['id']
        idAwayTeam = awayTeam['team']['id']
        shotsOnGoalHomeTeam = homeTeam['statistics'][0]['value']
        shotsOnGoalAwayTeam = awayTeam['statistics'][0]['value']
        shotsInsideBoxHomeTeam = homeTeam['statistics'][4]['value']
        shotsInsideBoxAwayTeam = awayTeam['statistics'][4]['value']
        totalShotsHomeTeam = homeTeam['statistics'][2]['value']
        totalShotsAwayTeam = awayTeam['statistics'][2]['value']
        ballPossessionHomeTeam = homeTeam['statistics'][9]['value']
        ballPossessionAwayTeam = awayTeam['statistics'][9]['value']
        row = {'idFixture':idFixture,'idHomeTeam':idHomeTeam, 'idAwayTeam':idAwayTeam,
                'shotsOnGoalHomeTeam':shotsOnGoalHomeTeam, 'shotsOnGoalAwayTeam':shotsOnGoalAwayTeam,
                'shotsInsideBoxHomeTeam':shotsInsideBoxHomeTeam, 'shotsInsideBoxAwayTeam':shotsInsideBoxAwayTeam,
                'totalShotsHomeTeam':totalShotsHomeTeam, 'totalShotsAwayTeam':totalShotsAwayTeam,
                'ballPossessionHomeTeam':ballPossessionHomeTeam, 'ballPossessionAwayTeam':ballPossessionAwayTeam}
        df = df.append(row, ignore_index=True)
    # Sleep 3 seconds between each statistics request to avoid the 30 requests / minute API Football limitation
    # WARNING!!! API Football is free until 100 requests / day, and costs around €0.00450 / request beyond
    #            If you run this script after the league's 10th round, it will involve cost
        time.sleep(3)
    # Upload statistics as a csv file into 'processed-data' folder
    prefix = 'processed-data/api-football/statistics/'
    name = ''.join(['statistics-', todayDate, '.csv'])
    uploadCsvToS3(df, dataLakeBucketName, s3_client, prefix, name)

    print('API Football data received and processed successfully!')

if __name__ == '__main__':

    schedule.every().tuesday.at("08:00").do(main)

    while True:
        schedule.run_pending()
        time.sleep(1)
