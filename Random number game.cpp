/*
#include<iostream>
#include<conio.h>
#include<cstdlib>
using namespace std;

int main()
{
    while(1){
    int guessNumber, randomNumber;

        cout<<"Enter the Number 1 to 5: " ;
        cin>>guessNumber;
      randomNumber=rand()%2+1;

      if(guessNumber==randomNumber)
        {
      cout<<"You have won!" <<endl<<endl;
      }
      else{
        cout<<"You lost!!!! Try again...."<<endl<<endl;
        cout<<"Random number is: "<<randomNumber<<endl;
      }
}
    getch();
}



*/

#include<iostream>
#include<conio.h>
#include<cstdlib>
using namespace std;

int main()
{

while(1)

    {
    int guessNumber, randomNumber;

    cout<<"Enter the number between 1 to 5: ";
    cin>>guessNumber;

        randomNumber=rand()%5+1;

        if(guessNumber==randomNumber){
            cout<<"You have won....................! "<<endl<<endl;
        }
        else{

                cout<<"You lost the game!!!!! Try again,,,!"<<endl<<endl;
    cout<<"Random Number is: " <<randomNumber<<endl<<endl;
        }
    }
    getch();

}
