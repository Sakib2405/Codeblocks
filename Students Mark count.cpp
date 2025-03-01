#include<iostream>
#include<conio.h>
using namespace std;

int main()

{
    int n;
    cout<<"Enter the total students: ";
    cin>>n;
    int students[n];

    for(int i=0; i<n; i++)
    {

        cout<<endl<<"Student "<<i+1<<" information: "<<endl;

        int sum=0, marks[5];

        for(int i=0; i<5; i++)
        {
            cout<<"Mark of sub"<<i+1<<" is: ";
            cin>>marks[i];

            sum=sum+marks[i];
            if(i>3)
            {
                cout<<"Total Mark is: "<<sum<<endl<<endl;
            }
        }


    }
    for(int i=0; i<n; i++)
    {

    }


    getch();
}


// {
// cout<<"Sub_"<<i+1<<"mark is: ";
// }
